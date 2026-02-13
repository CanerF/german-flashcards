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
-- Trigger function to prevent inserts/updates to cards unless the current DB session user matches deck owner
CREATE OR REPLACE FUNCTION check_card_owner() RETURNS trigger AS $$
DECLARE
    deck_owner INTEGER;
    current_user_id INTEGER;
    current_is_admin BOOLEAN := FALSE;
BEGIN
    SELECT owner_id INTO deck_owner FROM decks WHERE id = NEW.deck_id;
    BEGIN
        current_user_id := current_setting('app.current_user_id')::integer;
    EXCEPTION WHEN others THEN
        current_user_id := NULL;
    END;

    IF current_user_id IS NOT NULL THEN
        BEGIN
            SELECT is_admin INTO current_is_admin FROM users WHERE id = current_user_id;
        EXCEPTION WHEN others THEN
            current_is_admin := FALSE;
        END;
    END IF;

    -- If the deck is shared (owner_id IS NULL) allow only admins to modify
    IF deck_owner IS NULL THEN
        IF NOT current_is_admin THEN
            RAISE EXCEPTION 'Permission denied: cannot modify shared deck.';
        END IF;
        RETURN NEW;
    END IF;

    -- For owned decks, only the owner or admins can modify
    IF current_user_id IS NULL OR (current_user_id <> deck_owner AND NOT current_is_admin) THEN
        RAISE EXCEPTION 'Permission denied: not deck owner.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_card_owner ON cards;
CREATE TRIGGER enforce_card_owner
BEFORE INSERT OR UPDATE ON cards
FOR EACH ROW EXECUTE FUNCTION check_card_owner();
"""

try:
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(sql)
        print("Trigger migration applied: card ownership enforcement installed.")
    conn.close()
except Exception as e:
    print("Migration failed:", e)
    raise
