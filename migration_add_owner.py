import os
import psycopg2
from dotenv import load_dotenv

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

sql = """
ALTER TABLE decks
    ADD COLUMN IF NOT EXISTS owner_id INTEGER REFERENCES users(id);
"""

try:
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(sql)
        print("Migration applied: owner_id column added (or already existed).")
    conn.close()
except Exception as e:
    print("Migration failed:", e)
    raise
