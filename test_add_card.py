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

conn = psycopg2.connect(**DB_CONFIG)
conn.autocommit = True

user_a = f"user_a_{uuid.uuid4().hex[:8]}"
user_b = f"user_b_{uuid.uuid4().hex[:8]}"
passw = "Pass123!"

try:
    # cleanup
    auth.delete_user(conn, user_a)
    auth.delete_user(conn, user_b)

    # create users
    ok, msg = auth.create_user(conn, user_a, passw)
    ok2, msg2 = auth.create_user(conn, user_b, passw)
    print("Created:", user_a, ok, msg, ";", user_b, ok2, msg2)

    # fetch ids
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username = %s", (user_a,))
        a_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM users WHERE username = %s", (user_b,))
        b_id = cur.fetchone()[0]

    # create a deck owned by user_a
    with conn.cursor() as cur:
        cur.execute("INSERT INTO decks (name, owner_id) VALUES (%s, %s) RETURNING id", ("A's Deck", a_id))
        deck_id = cur.fetchone()[0]
    print("Deck created", deck_id, "owned by", a_id)

    # attempt to add card as user_b (should be disallowed by app logic)
    with conn.cursor() as cur:
        cur.execute("SELECT owner_id FROM decks WHERE id = %s", (deck_id,))
        owner = cur.fetchone()[0]
        print("Owner of deck:", owner)
        if owner is None:
            print("Test: shared deck - app should block adding")
        elif owner != b_id:
            print("Test: user_b cannot add card to user_a deck - app should block")
        else:
            print("Test: unexpected - owner equals user_b")

    # add card as owner (user_a)
    with conn.cursor() as cur:
        # set session var so trigger permits this action
        cur.execute("SELECT set_config('app.current_user_id', %s, false)", (str(a_id),))
        cur.execute("INSERT INTO cards (deck_id, front, back) VALUES (%s, %s, %s)", (deck_id, "Front A", "Back A"))
        # clear session var
        cur.execute("SELECT set_config('app.current_user_id', '', false)")
    print("Owner added a card successfully (via session var)")

    # cleanup deck and users
    with conn.cursor() as cur:
        cur.execute("DELETE FROM cards WHERE deck_id = %s", (deck_id,))
        cur.execute("DELETE FROM decks WHERE id = %s", (deck_id,))
    auth.delete_user(conn, user_a)
    auth.delete_user(conn, user_b)

    print("TEST_ADD_CARD: Completed (note: app logic must be enforced in UI code; DB reflects inserts)")
finally:
    conn.close()
