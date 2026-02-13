import os
import psycopg2
import uuid
from dotenv import load_dotenv
import auth

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

username = f"ui_test_{uuid.uuid4().hex[:8]}"
password = "UiTestPass!23"

print("Starting simulated UI test for registration")
conn = psycopg2.connect(**DB_CONFIG)
conn.autocommit = True

# Ensure clean
auth.delete_user(conn, username)

success, msg = auth.create_user(conn, username, password)
print("create_user ->", success, msg)

exists = auth.user_exists(conn, username)
print("user_exists ->", exists)

# Cleanup
auth.delete_user(conn, username)
print("deleted test user")

if success and exists:
    print("UI SIM TEST: SUCCESS")
else:
    print("UI SIM TEST: FAILED")

conn.close()
