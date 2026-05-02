# Importa as funções principais do Flask pra criar rotas, renderizar páginas,
# lidar com requisições, redirecionar, sessão, mensagens e JSON
from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify)

# Importa funções de localização (estados, cidades e coordenadas)
from brasil_geo import get_states, get_cities, get_coords

# Importa um módulo auxiliar com funções do sistema (usuário, banco, etc.)
import func as fn

# Cria a aplicação Flask
app = Flask(__name__)

# Chave secreta usada pra proteger sessões (login do usuário)
app.secret_key = 'senha_super_secreta'


# ─────────────────────────────────────────────────────────────────────────────
# AUTH (AUTENTICAÇÃO)
# ─────────────────────────────────────────────────────────────────────────────

# Rota principal
@app.route('/')
def index():
    # Se o usuário estiver logado, vai pro dashboard
    # Senão, manda pro login
    return redirect(url_for('dashboard') if 'user' in session else url_for('login'))


# Rota de login (GET = abrir página / POST = enviar dados)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Pega os dados do formulário e remove espaços extras
        name     = request.form.get('name', '').strip()
        password = request.form.get('password', '').strip()

        # Verifica se existe usuário com essas credenciais
        if fn.get_user_by_credentials(name, password):
            # Salva o usuário na sessão (login)
            session['user'] = name
            return redirect(url_for('dashboard'))

        # Caso esteja errado
        flash('Nome ou senha incorretos.', 'error')

    # Renderiza a página de login
    return render_template('login.html')


# Rota de cadastro
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        # Pega os dados do formulário
        name     = request.form.get('name', '').strip()
        cpf      = request.form.get('cpf', '').strip()
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        # Tenta registrar o usuário
        success, error = fn.register_user(name, cpf, email, password)

        if success:
            flash('Conta criada com sucesso! Faça login.', 'success')
            return redirect(url_for('login'))

        # Se deu erro, mostra mensagem
        flash(error, 'error')

    return render_template('register.html')


# Rota de logout
@app.route('/logout')
def logout():
    # Limpa a sessão (desloga o usuário)
    session.clear()
    return redirect(url_for('login'))


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

# Página principal do usuário
@app.route('/dashboard')
def dashboard():
    # Se não estiver logado, manda pro login
    if 'user' not in session:
        return redirect(url_for('login'))

    # Renderiza o dashboard com os dados do usuário
    return render_template('dashboard.html', user=fn.get_user(session['user']))


# Rota para saque
@app.route('/withdraw', methods=['POST'])
def withdraw():
    if 'user' not in session:
        return redirect(url_for('login'))

    try:
        # Pega o valor e converte pra float
        amount = float(request.form.get('amount', 0))
    except ValueError:
        flash('Valor inválido.', 'error')
        return redirect(url_for('dashboard'))

    # Executa o saque
    success, message = fn.do_withdraw(session['user'], amount)

    # Mostra mensagem de sucesso ou erro
    flash(message, 'success' if success else 'error')
    return redirect(url_for('dashboard'))


# Rota para depósito
@app.route('/deposit', methods=['POST'])
def deposit():
    if 'user' not in session:
        return redirect(url_for('login'))

    try:
        # Converte valor
        amount = float(request.form.get('amount', 0))
    except ValueError:
        flash('Valor inválido.', 'error')
        return redirect(url_for('dashboard'))

    # Executa depósito
    success, message = fn.do_deposit(session['user'], amount)

    flash(message, 'success' if success else 'error')
    return redirect(url_for('dashboard'))


# ─────────────────────────────────────────────────────────────────────────────
# CHECKOUT (COMPRA)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Pega dados do usuário e lista de estados
    user   = fn.get_user(session['user'])
    states = get_states()

    if request.method == 'POST':
        # Dados da compra
        product    = request.form.get('product', '').strip()
        vendor     = request.form.get('vendor', '').strip()
        cost_str   = request.form.get('cost', '').strip()
        state_code = request.form.get('state', '').strip()
        city_name  = request.form.get('city', '').strip()

        # Verifica se todos os campos foram preenchidos
        if not all([product, vendor, cost_str, state_code, city_name]):
            flash('Preencha todos os campos.', 'error')
            return render_template('checkout.html', user=user, states=states)

        try:
            # Converte custo
            cost = float(cost_str)

            # Não pode ser zero ou negativo
            if cost <= 0:
                raise ValueError
        except ValueError:
            flash('Custo inválido.', 'error')
            return render_template('checkout.html', user=user, states=states)

        # Verifica saldo
        if cost > user['bal']:
            flash('Saldo insuficiente para realizar esta compra.', 'error')
            return render_template('checkout.html', user=user, states=states)

        # Pega coordenadas da cidade
        coords = get_coords(state_code, city_name)
        if not coords:
            flash('Localização inválida.', 'error')
            return render_template('checkout.html', user=user, states=states)

        lat, lng = coords

        # Verifica possível fraude (distância de compras anteriores)
        is_fraud, dist_km, worst = fn.check_fraud(user['id'], lat, lng)

        if is_fraud:
            # Marca conta como suspeita
            fn.do_flag_account(user['id'])

            flash(
                f'⚠ Compra bloqueada por suspeita de fraude. '
                f'Distância detectada: {dist_km} km da última localização conhecida '
                f'({worst["city"]}, {worst["state"]} em {worst["purchased_at"]}). '
                f'Sua conta foi sinalizada. Entre em contato com o suporte.',
                'error'
            )
            return render_template('checkout.html', user=user, states=states)

        # Realiza a compra
        fn.do_purchase(user['id'], product, vendor, cost, state_code, city_name, lat, lng)

        flash(f'Compra de "{product}" por R${cost:.2f} realizada com sucesso!', 'success')
        return redirect(url_for('purchases'))

    return render_template('checkout.html', user=user, states=states)


# ─────────────────────────────────────────────────────────────────────────────
# HISTÓRICO DE COMPRAS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/purchases')
def purchases():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Busca usuário e histórico de compras
    user    = fn.get_user(session['user'])
    history = fn.get_purchase_history(user['id'])

    return render_template('purchases.html', user=user, history=history)


# ─────────────────────────────────────────────────────────────────────────────
# API (RETORNA DADOS EM JSON)
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/cities/<state_code>')
def api_cities(state_code):
    # Retorna as cidades do estado em formato JSON
    return jsonify(get_cities(state_code.upper()))


# ─────────────────────────────────────────────────────────────────────────────
# DESBLOQUEIO DE CONTA
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/unflag', methods=['POST'])
def unflag():
    if 'user' not in session:
        return redirect(url_for('login'))

    # Remove o bloqueio da conta
    fn.do_unflag_account(session['user'])

    flash('Conta desbloqueada com sucesso.', 'success')
    return redirect(url_for('dashboard'))


# ─────────────────────────────────────────────────────────────────────────────
# INÍCIO DA APLICAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Inicializa o banco de dados
    fn.init_db()

    # Migra senhas (provavelmente aplica hash ou algo assim)
    fn.migrate_passwords()

    # Roda o servidor
    app.run(host='0.0.0.0', port=5000, debug=True)
