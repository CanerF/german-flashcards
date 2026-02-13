import csv
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

WORDLIST_PATH = r"C:\Users\caner\Downloads\wordlist1.txt"
DECK_NAME = "Lektion-9"

if not DB_CONFIG["password"]:
    print("ERROR: DB_PASSWORD not set in environment. Abort.")
    raise SystemExit(1)

if not os.path.exists(WORDLIST_PATH):
    print(f"ERROR: wordlist not found: {WORDLIST_PATH}")
    raise SystemExit(1)

conn = psycopg2.connect(**DB_CONFIG)
conn.autocommit = True

try:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = 'admin'")
        row = cur.fetchone()
        if not row:
            print("ERROR: admin user not found. Create admin first.")
            raise SystemExit(1)
        admin_user_id = row[0]

        cur.execute("SELECT set_config('app.current_user_id', %s, false)", (str(admin_user_id),))
        cur.execute("SELECT id FROM decks WHERE name = %s AND owner_id IS NULL", (DECK_NAME,))
        deck_row = cur.fetchone()
        if deck_row:
            deck_id = deck_row[0]
            print(f"Using existing shared deck '{DECK_NAME}' (id={deck_id}).")
        else:
            cur.execute(
                "INSERT INTO decks (name, owner_id) VALUES (%s, NULL) RETURNING id",
                (DECK_NAME,)
            )
            deck_id = cur.fetchone()[0]
            print(f"Created shared deck '{DECK_NAME}' (id={deck_id}).")

    inserted = 0
    skipped = 0
    with open(WORDLIST_PATH, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            front = row[0].strip()
            back = row[1].strip()
            if not front or not back:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO cards (deck_id, front, back)
                    SELECT %s, %s, %s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM cards WHERE deck_id = %s AND front = %s AND back = %s
                    )
                    """,
                    (deck_id, front, back, deck_id, front, back)
                )
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    skipped += 1

    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.current_user_id', '', false)")

    print(f"Import completed. Inserted={inserted}, skipped={skipped}.")
finally:
    conn.close()
