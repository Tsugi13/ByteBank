from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify)
from brasil_geo import get_states, get_cities, get_coords
import func as fn

app = Flask(__name__)
app.secret_key = 'senha_super_secreta'  


# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('home') if 'user' in session else url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        password = request.form.get('password', '').strip()

        if fn.get_user_by_credentials(name, password):
            session['user'] = name
            return redirect(url_for('home'))
        flash('Nome ou senha incorretos.', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        cpf      = request.form.get('cpf', '').strip()
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()

        success, error = fn.register_user(name, cpf, email, password)
        if success:
            flash('Conta criada com sucesso! Faça login.', 'success')
            return redirect(url_for('login'))
        flash(error, 'error')

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/home')
def home():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('home.html', user=fn.get_user(session['user']))


@app.route('/withdraw', methods=['POST'])
def withdraw():
    if 'user' not in session:
        return redirect(url_for('login'))
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        flash('Valor inválido.', 'error')
        return redirect(url_for('dashboard'))

    success, message = fn.do_withdraw(session['user'], amount)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('dashboard'))


@app.route('/deposit', methods=['POST'])
def deposit():
    if 'user' not in session:
        return redirect(url_for('login'))
    try:
        amount = float(request.form.get('amount', 0))
    except ValueError:
        flash('Valor inválido.', 'error')
        return redirect(url_for('dashboard'))

    success, message = fn.do_deposit(session['user'], amount)
    flash(message, 'success' if success else 'error')
    return redirect(url_for('dashboard'))


# ─────────────────────────────────────────────────────────────────────────────
# CHECKOUT
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user' not in session:
        return redirect(url_for('login'))

    user   = fn.get_user(session['user'])
    states = get_states()

    if request.method == 'POST':
        product    = request.form.get('product', '').strip()
        vendor     = request.form.get('vendor', '').strip()
        cost_str   = request.form.get('cost', '').strip()
        state_code = request.form.get('state', '').strip()
        city_name  = request.form.get('city', '').strip()

        if not all([product, vendor, cost_str, state_code, city_name]):
            flash('Preencha todos os campos.', 'error')
            return render_template('checkout.html', user=user, states=states)

        try:
            cost = float(cost_str)
            if cost <= 0:
                raise ValueError
        except ValueError:
            flash('Custo inválido.', 'error')
            return render_template('checkout.html', user=user, states=states)

        if cost > user['bal']:
            flash('Saldo insuficiente para realizar esta compra.', 'error')
            return render_template('checkout.html', user=user, states=states)

        coords = get_coords(state_code, city_name)
        if not coords:
            flash('Localização inválida.', 'error')
            return render_template('checkout.html', user=user, states=states)

        lat, lng = coords

        is_fraud, dist_km, worst = fn.check_fraud(user['id'], lat, lng)
        if is_fraud:
            fn.do_flag_account(user['id'])
            flash(
                f'⚠ Compra bloqueada por suspeita de fraude. '
                f'Distância detectada: {dist_km} km da última localização conhecida '
                f'({worst["city"]}, {worst["state"]} em {worst["purchased_at"]}). '
                f'Sua conta foi sinalizada. Entre em contato com o suporte.',
                'error'
            )
            return render_template('checkout.html', user=user, states=states)

        fn.do_purchase(user['id'], product, vendor, cost, state_code, city_name, lat, lng)
        flash(f'Compra de "{product}" por R${cost:.2f} realizada com sucesso!', 'success')
        return redirect(url_for('purchases'))

    return render_template('checkout.html', user=user, states=states)


# ─────────────────────────────────────────────────────────────────────────────
# PURCHASES HISTORY
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/purchases')
def purchases():
    if 'user' not in session:
        return redirect(url_for('login'))
    user    = fn.get_user(session['user'])
    history = fn.get_purchase_history(user['id'])
    return render_template('purchases.html', user=user, history=history)


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/cities/<state_code>')
def api_cities(state_code):
    return jsonify(get_cities(state_code.upper()))


# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT FLAGS
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/unflag', methods=['POST'])
def unflag():
    if 'user' not in session:
        return redirect(url_for('login'))
    fn.do_unflag_account(session['user'])
    flash('Conta desbloqueada com sucesso.', 'success')
    return redirect(url_for('dashboard'))


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    fn.init_db()
    fn.migrate_passwords()
    app.run(host='0.0.0.0', port=5000, debug=True)
