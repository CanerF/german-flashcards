import os
import psycopg2
import bcrypt
from dotenv import load_dotenv
import uuid

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "aws-0-eu-central-1.pooler.supabase.com"),
    "database": os.getenv("DB_NAME", "postgres"),
    "user": os.getenv("DB_USER", "postgres.djtryoqdcywczxtyvomw"),
    "password": os.getenv("DB_PASSWORD"),
    "port": os.getenv("DB_PORT", "6543"),
    "sslmode": "require",
    "connect_timeout": 10
}

if not DB_CONFIG["password"]:
    print("ERROR: DB_PASSWORD not set in environment. Abort.")
    raise SystemExit(1)

username = f"test_user_{uuid.uuid4().hex[:8]}"
password = "TestPass123!"

try:
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
except Exception as e:
    print("DB connection failed:", e)
    raise SystemExit(1)

try:
    with conn.cursor() as cur:
        # Ensure no pre-existing user (shouldn't be)
        cur.execute("DELETE FROM users WHERE username = %s", (username,))

        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, hashed))
        print(f"Inserted user: {username}")

        cur.execute("SELECT id, username FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        if row:
            print(f"Verified user exists with id={row[0]} username={row[1]}")
        else:
            print("Verification failed: user not found after insert")

        # Cleanup
        cur.execute("DELETE FROM users WHERE username = %s", (username,))
        print(f"Cleaned up user: {username}")

    conn.close()
    print("TEST: SUCCESS")
except Exception as e:
    print("TEST: FAILED", e)
    raise
