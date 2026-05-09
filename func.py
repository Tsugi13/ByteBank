# Importa o SQLite pra trabalhar com banco de dados local
import sqlite3

# Importa funções matemáticas (usado no cálculo de distância)
import math

# Biblioteca usada pra criptografar senha (segurança)
import bcrypt

# Pra trabalhar com data e hora
from datetime import datetime

# Importa configurações do sistema (ex: caminho do banco, limite de fraude)
import config as cfg


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────────────────────────────────────

def get_conn():
    """Returns a SQLite connection with row_factory set to sqlite3.Row."""
    # Abre conexão com o banco usando o caminho definido no config
    conn = sqlite3.connect(cfg.DB_PATH)

    # Permite acessar colunas pelo nome (tipo dicionário)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Creates all tables if they don't exist and handles schema migrations."""
    # Abre conexão com o banco
    with get_conn() as conn:

        # Cria tabela de clientes se não existir
        conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                name      TEXT    NOT NULL,
                cpf       TEXT    NOT NULL UNIQUE,
                email     TEXT    NOT NULL UNIQUE,
                password  TEXT    NOT NULL,
                cred_lim  REAL    DEFAULT 0.0,
                bal       REAL    DEFAULT 0.0,
                flagged   INTEGER DEFAULT 0
            )
        """)

        # Tenta adicionar coluna "flagged" (caso banco seja antigo e não tenha)
        try:
            conn.execute("ALTER TABLE clients ADD COLUMN flagged INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Se já existe, ignora sem erro

        # Cria tabela de compras
        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id    INTEGER NOT NULL,
                product      TEXT    NOT NULL,
                vendor       TEXT    NOT NULL,
                cost         REAL    NOT NULL,
                state        TEXT    NOT NULL,
                city         TEXT    NOT NULL,
                lat          REAL    NOT NULL,
                lng          REAL    NOT NULL,
                purchased_at TEXT    NOT NULL,
                FOREIGN KEY (client_id) REFERENCES clients(id)
            )
        """)

        # Salva alterações
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# CLIENT QUERIES (CONSULTAS DE USUÁRIO)
# ─────────────────────────────────────────────────────────────────────────────

def get_user(name: str) -> dict | None:
    """Returns a client dict by name, or None if not found."""
    with get_conn() as conn:
        # Busca usuário pelo nome
        row = conn.execute(
            "SELECT id, name, bal, cred_lim, flagged FROM clients WHERE name = ?",
            (name,)
        ).fetchone()

    # Se encontrou, retorna como dicionário
    return dict(row) if row else None


def get_user_by_credentials(name: str, password: str) -> dict | None:
    """
    Looks up a client by name and verifies the password.
    Returns the client row dict on success, or None on failure.
    """
    with get_conn() as conn:
        # Busca usuário pelo nome
        row = conn.execute(
            "SELECT name, password FROM clients WHERE name = ?", (name,)
        ).fetchone()

    # Verifica senha (comparando com hash)
    if row and verify_password(password, row['password']):
        return dict(row)

    return None


def register_user(name: str, cpf: str, email: str, password: str) -> tuple[bool, str]:
    """
    Inserts a new client into the database.
    Returns (success: bool, error_message: str).
    On success, error_message is an empty string.
    """
    with get_conn() as conn:
        # Verifica se CPF já existe
        cpf_exists   = conn.execute("SELECT 1 FROM clients WHERE cpf=?",   (cpf,)).fetchone()

        # Verifica se email já existe
        email_exists = conn.execute("SELECT 1 FROM clients WHERE email=?", (email,)).fetchone()

    if cpf_exists:
        return False, 'CPF já cadastrado.'
    if email_exists:
        return False, 'Email já cadastrado.'

    # Criptografa senha antes de salvar
    hashed = hash_password(password)

    with get_conn() as conn:
        # Insere novo usuário
        conn.execute(
            "INSERT INTO clients (name, cpf, email, password, cred_lim, bal) VALUES (?,?,?,?,?,?)",
            (name, cpf, email, hashed, 0.0, 0.0)
        )
        conn.commit()

    return True, ''


# ─────────────────────────────────────────────────────────────────────────────
# OPERAÇÕES BANCÁRIAS
# ─────────────────────────────────────────────────────────────────────────────

def do_withdraw(name: str, amount: float) -> tuple[bool, str]:
    """
    Deducts `amount` from the named client's balance.
    Returns (success: bool, message: str).
    """
    with get_conn() as conn:
        # Busca saldo
        row = conn.execute("SELECT bal FROM clients WHERE name=?", (name,)).fetchone()

        if not row:
            return False, 'Usuário não encontrado.'

        # Validação de valor
        if amount <= 0:
            return False, 'O valor deve ser maior que zero.'

        # Verifica saldo suficiente
        if amount > row['bal']:
            return False, 'Saldo insuficiente.'

        # Atualiza saldo
        conn.execute("UPDATE clients SET bal = bal - ? WHERE name=?", (amount, name))
        conn.commit()

    # Formata valor pra padrão BR
    return True, f'Saque de R${amount:,.2f} realizado com sucesso!'.replace(',', 'X').replace('.', ',').replace('X', '.')


def do_deposit(name: str, amount: float) -> tuple[bool, str]:
    """
    Adds `amount` to the named client's balance.
    Returns (success: bool, message: str).
    """
    if amount <= 0:
        return False, 'O valor deve ser maior que zero.'

    with get_conn() as conn:
        # Soma valor ao saldo
        conn.execute("UPDATE clients SET bal = bal + ? WHERE name=?", (amount, name))
        conn.commit()

    return True, f'Depósito de R${amount:,.2f} realizado com sucesso!'.replace(',', 'X').replace('.', ',').replace('X', '.')


def do_flag_account(client_id: int):
    """Marks a client account as flagged (suspicious activity detected)."""
    with get_conn() as conn:
        # Marca conta como suspeita
        conn.execute("UPDATE clients SET flagged=1 WHERE id=?", (client_id,))
        conn.commit()


def do_unflag_account(name: str):
    """Clears the fraud flag on a client account."""
    with get_conn() as conn:
        # Remove marcação de fraude
        conn.execute("UPDATE clients SET flagged=0 WHERE name=?", (name,))
        conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# COMPRAS
# ─────────────────────────────────────────────────────────────────────────────

def do_purchase(client_id: int, product: str, vendor: str, cost: float,
                state: str, city: str, lat: float, lng: float) -> bool:
    """
    Deducts cost from the client's balance and records the purchase.
    Returns True on success.
    """
    # Pega data e hora atual
    now = datetime.now().strftime('%d/%m/%Y %H:%M')

    with get_conn() as conn:
        # Subtrai valor da conta
        conn.execute("UPDATE clients SET bal = bal - ? WHERE id=?", (cost, client_id))

        # Registra a compra
        conn.execute("""
            INSERT INTO purchases (client_id, product, vendor, cost, state, city, lat, lng, purchased_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (client_id, product, vendor, cost, state, city, lat, lng, now))

        conn.commit()

    return True


def get_purchase_history(client_id: int) -> list[dict]:
    """Returns all purchases for a client, ordered newest first."""
    with get_conn() as conn:
        # Busca histórico ordenado do mais recente
        rows = conn.execute("""
            SELECT product, vendor, cost, state, city, purchased_at
            FROM purchases
            WHERE client_id = ?
            ORDER BY id DESC
        """, (client_id,)).fetchall()

    # Converte pra lista de dicionários
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# DETECÇÃO DE FRAUDE
# ─────────────────────────────────────────────────────────────────────────────

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Returns the great-circle distance in km between two lat/lng points."""
    # Raio da Terra em km
    R     = 6371.0

    # Converte pra radianos
    phi1  = math.radians(lat1)
    phi2  = math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlmbd = math.radians(lng2 - lng1)

    # Fórmula de Haversine (distância entre dois pontos no globo)
    a     = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmbd / 2) ** 2

    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def check_fraud(client_id: int, new_lat: float, new_lng: float) -> tuple[bool, float, dict | None]:
    """
    Compares a proposed purchase location against the last 5 purchases.
    """
    with get_conn() as conn:
        # Pega últimas 5 compras
        rows = conn.execute("""
            SELECT lat, lng, city, state, purchased_at
            FROM purchases
            WHERE client_id = ?
            ORDER BY id DESC
            LIMIT 5
        """, (client_id,)).fetchall()

    # Se não tiver histórico, não tem fraude
    if not rows:
        return False, 0.0, None

    max_dist    = 0.0
    worst_match = None

    # Calcula distância com base nas compras anteriores
    for row in rows:
        d = haversine(row['lat'], row['lng'], new_lat, new_lng)

        if d > max_dist:
            max_dist    = d
            worst_match = dict(row)

    # Compara com limite definido no config
    is_fraud = max_dist > cfg.FRAUD_DISTANCE_KM

    return is_fraud, round(max_dist, 1), worst_match


# ─────────────────────────────────────────────────────────────────────────────
# SENHAS
# ─────────────────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hashes a plain-text password using bcrypt."""
    # Gera hash da senha
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verifies a plain-text password against a bcrypt hash."""
    # Compara senha digitada com hash
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def migrate_passwords():
    """
    Converte senhas antigas (texto puro) para hash bcrypt.
    """
    with get_conn() as conn:
        rows    = conn.execute("SELECT id, password FROM clients").fetchall()
        updated = 0

        for row in rows:
            # Se não começa com $2, não é bcrypt ainda
            if not row['password'].startswith('$2'):
                conn.execute(
                    "UPDATE clients SET password=? WHERE id=?",
                    (hash_password(row['password']), row['id'])
                )
                updated += 1

        if updated:
            conn.commit()
            print(f"[ByteBank] Migrated {updated} plain-text password(s) to bcrypt.")
