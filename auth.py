import bcrypt


def create_user(conn, username: str, password: str) -> (bool, str):
    """Create a user in the database. Returns (success, message).
    This function expects an open connection `conn` (psycopg2) with autocommit configured as desired.
    """
    if not username or not password:
        return False, "Username and password are required"
    try:
        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, hashed_pw))
        return True, "Account created"
    except Exception as e:
        # Return a readable message (do not leak DB internals)
        return False, "Username already taken or error"


def user_exists(conn, username: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        return cur.fetchone() is not None


def delete_user(conn, username: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE username = %s", (username,))
