import csv
import flet as ft
import psycopg2
import bcrypt
import os
from datetime import date, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def main(page: ft.Page):
    # --- AYARLAR ---
    page.title = "German Flashcards Pro (Cloud)"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#0f172a"
    page.padding = 0
    page.window_width = 900
    page.window_height = 700

    # --- SUPABASE BAĞLANTISI (Secure Configuration) ---
    db_config = {
        "host": os.getenv("DB_HOST", "aws-0-eu-central-1.pooler.supabase.com"),
        "database": os.getenv("DB_NAME", "postgres"),
        "user": os.getenv("DB_USER", "postgres.djtryoqdcywczxtyvomw"),
        "password": os.getenv("DB_PASSWORD"),
        "port": os.getenv("DB_PORT", "6543"),
        "sslmode": "require",
        "connect_timeout": 10
    }

    # Check if password is set
    if not db_config["password"]:
        error_msg = "ERROR: Database password not found. Please create a .env file with DB_PASSWORD set."
        page.add(ft.Text(error_msg, color="red", size=16))
        print(error_msg)
        return

    try:
        conn = psycopg2.connect(**db_config)
        conn.autocommit = True
        print("✅ Connected to Supabase Cloud Database!")
    except psycopg2.OperationalError as e:
        error_msg = f"Connection Error: {str(e)}"
        page.add(ft.Text(error_msg, color="red", size=14))
        print(f"DB Error: {e}")
        return
    except Exception as e:
        error_msg = f"Unexpected Error: {str(e)}"
        page.add(ft.Text(error_msg, color="red", size=14))
        print(f"Error: {e}")
        return

    # --- DB ŞEMA KURULUMU (Otomatik) ---
    with conn.cursor() as cursor:
        # Tabloları oluştur
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decks (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                owner_id INTEGER REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id SERIAL PRIMARY KEY,
                deck_id INTEGER REFERENCES decks(id),
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                level INTEGER DEFAULT 0,
                interval_days INTEGER DEFAULT 1,
                ease_factor REAL DEFAULT 2.5,
                repetitions INTEGER DEFAULT 0,
                next_due DATE DEFAULT CURRENT_DATE
            );
        """)
        cursor.execute("""
            ALTER TABLE cards
                ADD COLUMN IF NOT EXISTS interval_days INTEGER,
                ADD COLUMN IF NOT EXISTS ease_factor REAL,
                ADD COLUMN IF NOT EXISTS repetitions INTEGER,
                ADD COLUMN IF NOT EXISTS next_due DATE;
        """)
        cursor.execute("""
            ALTER TABLE cards
                ALTER COLUMN interval_days SET DEFAULT 1,
                ALTER COLUMN ease_factor SET DEFAULT 2.5,
                ALTER COLUMN repetitions SET DEFAULT 0,
                ALTER COLUMN next_due SET DEFAULT CURRENT_DATE;
        """)
        # Admin Kullanıcısı
        admin_user_id = None
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        admin_row = cursor.fetchone()
        if admin_row:
            admin_user_id = admin_row[0]
        else:
            # Create admin user only if INITIAL_ADMIN_PASSWORD is provided in environment
            initial_admin_pw = os.getenv("INITIAL_ADMIN_PASSWORD")
            if initial_admin_pw:
                hashed_pw = bcrypt.hashpw(initial_admin_pw.encode('utf-8'), bcrypt.gensalt())
                cursor.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s) RETURNING id", 
                    ('admin', hashed_pw.decode('utf-8'), True)
                )
                admin_user_id = cursor.fetchone()[0]
                print("👤 Admin user created (user: admin)")
            else:
                print("⚠️ INITIAL_ADMIN_PASSWORD not set — admin user not created automatically.")

        if admin_user_id:
            try:
                cursor.execute("SELECT set_config('app.current_user_id', %s, false)", (str(admin_user_id),))
                cursor.execute("""
                    UPDATE cards
                    SET interval_days = COALESCE(interval_days, 1),
                        ease_factor = COALESCE(ease_factor, 2.5),
                        repetitions = COALESCE(repetitions, 0),
                        next_due = COALESCE(next_due, CURRENT_DATE);
                """)
            finally:
                cursor.execute("SELECT set_config('app.current_user_id', '', false)")
        else:
            print("⚠️ Admin not available — skipped card schedule backfill.")

        # Standart Deste - owned by admin to avoid database trigger issues
        cursor.execute("SELECT id FROM decks WHERE name = 'Standard German Start'")
        if not cursor.fetchone():
            try:
                print("📚 Creating Standard Deck on Cloud...")
                # Create deck owned by admin user (or NULL if no admin exists)
                cursor.execute("INSERT INTO decks (name, owner_id) VALUES ('Standard German Start', %s) RETURNING id", (admin_user_id,))
                std_deck_id = cursor.fetchone()[0]
                
                initial_words = [
                    ("Der Hund", "The Dog"), ("Die Katze", "The Cat"), ("Das Brot", "The Bread"),
                    ("Das Wasser", "The Water"), ("Hallo", "Hello"), ("Tschüss", "Goodbye"),
                    ("Danke", "Thank you"), ("Bitte", "Please")
                ]
                for front, back in initial_words:
                    cursor.execute("INSERT INTO cards (deck_id, front, back) VALUES (%s, %s, %s)", (std_deck_id, front, back))
                print("✅ Standard deck created successfully")
            except Exception as e:
                print(f"⚠️ Could not create standard deck: {e}")
                # Continue anyway - not critical for app to work

    # --- STATE ---
    current_user = None 
    current_deck_id = None 
    current_deck_owner_id = None
    current_card = None
    is_showing_answer = False

    # --- UI REFERANSLARI ---
    shared_decks_list = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
    my_decks_list = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True)
    decks_list = shared_decks_list  # legacy reference (not used for add)
    deck_dropdown = ft.Dropdown(
        label="Select Your Deck",
        width=420,
        border_radius=10,
        border_color="#334155",
        focused_border_color="#3b82f6",
        bgcolor="#0f172a",
        text_style=ft.TextStyle(size=14, color="#f1f5f9")
    )
    admin_user_list = ft.Column(scroll=ft.ScrollMode.AUTO)

    # --- DATA FONKSİYONLARI ---
    
    # Alert helpers first
    def close_alert(e):
        if hasattr(e.control, 'parent') and e.control.parent:
            dlg = e.control.parent.parent if hasattr(e.control.parent, 'parent') else None
            if dlg and dlg in page.overlay:
                dlg.open = False
                page.update()

    def show_alert(title, message):
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[ft.TextButton("OK", on_click=lambda e: close_dlg(dlg))],
            on_dismiss=lambda e: None
        )
        
        def close_dlg(dialog):
            dialog.open = False
            page.update()
        
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # Rename/Delete dialogs (defined early so button handlers can call them)
    rename_input = ft.TextField(label="New deck name", width=300)

    def show_rename_dialog(deck_id, current_name):
        try:
            rename_input.value = current_name
            
            def do_rename(e):
                new_name = rename_input.value
                if new_name:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE decks SET name = %s WHERE id = %s", (new_name, deck_id))
                dlg.open = False
                page.update()
                show_alert("Renamed", "Deck renamed successfully.")
                load_decks()
            
            def cancel_rename(e):
                dlg.open = False
                page.update()
            
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Rename Deck"),
                content=ft.Column([rename_input]),
                actions=[
                    ft.TextButton("Cancel", on_click=cancel_rename),
                    ft.TextButton("Rename", on_click=do_rename)
                ]
            )
            page.overlay.append(dlg)
            dlg.open = True
            page.update()
        except Exception as ex:
            print(f"[ERROR] Exception in show_rename_dialog: {ex}")
            import traceback
            traceback.print_exc()

    def show_delete_confirm(deck_id):
        try:
            def do_delete(e):
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM cards WHERE deck_id = %s", (deck_id,))
                    cur.execute("DELETE FROM decks WHERE id = %s", (deck_id,))
                dlg.open = False
                page.update()
                show_alert("Deleted", "Deck and its cards have been deleted.")
                load_decks()
            
            def cancel_delete(e):
                dlg.open = False
                page.update()
            
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Delete Deck"),
                content=ft.Text("Are you sure you want to delete this deck and its cards?"),
                actions=[
                    ft.TextButton("Cancel", on_click=cancel_delete),
                    ft.TextButton("Delete", on_click=do_delete)
                ]
            )
            page.overlay.append(dlg)
            dlg.open = True
            page.update()
        except Exception as ex:
            print(f"[ERROR] Exception in show_delete_confirm: {ex}")
            import traceback
            traceback.print_exc()

    # Rename/Delete button makers (now show_rename_dialog ve show_delete_confirm exist)
    def make_rename_button(did, dname, owner):
        def on_rename_click(e):
            try:
                if not current_user:
                    show_alert("Error", "Please login to rename decks.")
                    return
                if owner is None and not current_user['is_admin']:
                    show_alert("Error", "Only admins can rename shared decks.")
                    return
                if owner is not None and owner != current_user['id'] and not current_user['is_admin']:
                    show_alert("Error", "You don't have permission to rename this deck.")
                    return
                show_rename_dialog(did, dname)
            except Exception as ex:
                print(f"[ERROR] Exception in on_rename_click: {ex}")
                import traceback
                traceback.print_exc()
        
        # Always show buttons for own decks or admin
        if owner is None:
            visible = (current_user and current_user['is_admin'])
        else:
            visible = (current_user and (owner == current_user['id'] or current_user['is_admin']))
        
        return ft.IconButton(
            icon=ft.Icons.EDIT,
            icon_color="#60a5fa",
            icon_size=22,
            on_click=on_rename_click,
            visible=visible,
            tooltip="Rename Deck"
        )

    def make_delete_button(did, owner):
        def on_delete_click(e):
            try:
                if not current_user:
                    show_alert("Error", "Please login to delete decks.")
                    return
                if owner is None and not current_user['is_admin']:
                    show_alert("Error", "Only admins can delete shared decks.")
                    return
                if owner is not None and owner != current_user['id'] and not current_user['is_admin']:
                    show_alert("Error", "You don't have permission to delete this deck.")
                    return
                show_delete_confirm(did)
            except Exception as ex:
                print(f"[ERROR] Exception in on_delete_click: {ex}")
                import traceback
                traceback.print_exc()
        
        # Always show buttons for own decks or admin
        if owner is None:
            visible = (current_user and current_user['is_admin'])
        else:
            visible = (current_user and (owner == current_user['id'] or current_user['is_admin']))
        
        return ft.IconButton(
            icon=ft.Icons.DELETE,
            icon_color="#f87171",
            icon_size=22,
            on_click=on_delete_click,
            visible=visible,
            tooltip="Delete Deck"
        )

    def load_decks():
        # Hover effect for deck cards
        def on_deck_hover(e, card):
            if e.data == "true":
                card.scale = 1.02
                card.shadow = ft.BoxShadow(
                    spread_radius=2,
                    blur_radius=25,
                    color="#00000080",
                    offset=ft.Offset(0, 8)
                )
            else:
                card.scale = 1.0
                card.shadow = ft.BoxShadow(
                    spread_radius=1,
                    blur_radius=15,
                    color="#0000004D",
                    offset=ft.Offset(0, 4)
                )
            card.update()
        
        shared_decks_list.controls.clear()
        my_decks_list.controls.clear()
        options_owned = []
        with conn.cursor() as cur:
            # Show shared decks (owner_id IS NULL) plus decks owned by current user
            if current_user:
                cur.execute("""
                    SELECT d.id, d.name, d.owner_id, COUNT(c.id)
                    FROM decks d
                    LEFT JOIN cards c ON d.id = c.deck_id
                    WHERE d.owner_id IS NULL OR d.owner_id = %s
                    GROUP BY d.id, d.name, d.owner_id ORDER BY d.id
                """, (current_user['id'],))
            else:
                cur.execute("""
                    SELECT d.id, d.name, d.owner_id, COUNT(c.id)
                    FROM decks d
                    LEFT JOIN cards c ON d.id = c.deck_id
                    WHERE d.owner_id IS NULL
                    GROUP BY d.id, d.name, d.owner_id ORDER BY d.id
                """)
            rows = cur.fetchall()
            for deck_id, name, owner_id, count in rows:
                if owner_id is None:
                    label = f"{name} (Shared)"
                    target_list = shared_decks_list
                elif current_user and owner_id == current_user['id']:
                    label = f"{name} (My Deck)"
                    target_list = my_decks_list
                    options_owned.append(ft.dropdown.Option(key=str(deck_id), text=name))
                else:
                    label = f"{name} (Other)"
                    target_list = shared_decks_list

                # Buttons: Play always; Rename/Delete via helper functions
                play_btn = ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.PLAY_ARROW, color="white", size=20),
                        ft.Text("PLAY", size=14, weight="bold", color="white")
                    ], spacing=5, alignment=ft.MainAxisAlignment.CENTER),
                    bgcolor="#0d9488",
                    padding=ft.Padding(left=15, right=15, top=10, bottom=10),
                    border_radius=8,
                    on_click=lambda e, did=deck_id: start_practice(did),
                    ink=True,
                    animate=ft.Animation(200, "easeOut")
                )
                rename_btn = make_rename_button(deck_id, name, owner_id)
                delete_btn = make_delete_button(deck_id, owner_id)

                # Determine gradient colors based on deck type
                if owner_id is None:
                    # Shared decks - blue gradient
                    gradient_colors = ["#1e3a8a", "#1e293b"]
                    badge_color = "#3b82f6"
                    badge_icon = ft.Icons.PUBLIC
                else:
                    # User decks - purple gradient
                    gradient_colors = ["#581c87", "#1e293b"]
                    badge_color = "#a855f7"
                    badge_icon = ft.Icons.PERSON

                deck_card = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Container(
                                content=ft.Icon(badge_icon, color="white", size=16),
                                bgcolor=badge_color,
                                padding=5,
                                border_radius=5
                            ),
                            ft.Text(label, size=18, weight="bold", expand=True),
                        ], spacing=10),
                        ft.Container(height=5),
                        ft.Row([
                            ft.Icon(ft.Icons.STYLE, color="#64748b", size=16),
                            ft.Text(f"{count} Cards", size=13, color="#94a3b8")
                        ], spacing=5),
                        ft.Container(height=10),
                        ft.Row([
                            play_btn,
                            ft.Container(expand=True),
                            rename_btn,
                            delete_btn
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
                    ], spacing=0),
                    gradient=ft.LinearGradient(
                        begin=ft.Alignment(-1, -1),
                        end=ft.Alignment(1, 1),
                        colors=gradient_colors
                    ),
                    padding=20,
                    border_radius=15,
                    margin=ft.Margin(bottom=15, left=0, right=0, top=0),
                    shadow=ft.BoxShadow(
                        spread_radius=1,
                        blur_radius=15,
                        color="#0000004D",
                        offset=ft.Offset(0, 4)
                    ),
                    animate=ft.Animation(300, "easeOut"),
                    on_hover=lambda e: on_deck_hover(e, deck_card)
                )
                
                target_list.controls.append(deck_card)

        # Populate dropdown with only decks owned by the user (for adding cards)
        deck_dropdown.options = options_owned
        if options_owned:
            deck_dropdown.value = options_owned[0].key
        else:
            deck_dropdown.value = None
        page.update()

    # --- AUTH FONKSİYONLARI ---
    def login(e):
        nonlocal current_user
        username = txt_username.value
        password = txt_password.value
        
        # Hataları sıfırla
        txt_username.error_text = ""
        txt_password.error_text = ""
        error_banner.visible = False

        with conn.cursor() as cur:
            cur.execute("SELECT id, username, password_hash, is_admin FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
        
        if user:
            stored_hash = user[2].encode('utf-8')
            password_match = bcrypt.checkpw(password.encode('utf-8'), stored_hash)
            
            if password_match:
                current_user = {"id": user[0], "username": user[1], "is_admin": user[3]}
                page.snack_bar = ft.SnackBar(ft.Text(f"Welcome, {current_user['username']}!"))
                page.snack_bar.open = True
                
                view_login.visible = False
                app_layout.visible = True
                if current_user['is_admin']:
                    btn_admin_panel.visible = True
                else:
                    btn_admin_panel.visible = False
                try:
                    with conn.cursor() as cur2:
                        cur2.execute("SELECT set_config('app.current_user_id', %s, false)", (str(current_user['id']),))
                except Exception:
                    pass
                load_decks()
                update_debug_info()
                page.update()
            else:
                # YANLIŞ ŞİFRE - KIRMIZI BANNER GÖSTER
                error_banner.content.value = "❌ Yanlış şifre!"
                error_banner.visible = True
                txt_password.error_text = "Yanlış şifre"
                page.update()
        else:
            # KULLANICIBULUNAMADI - KIRMIZI BANNER GÖSTER
            error_banner.content.value = "❌ Kullanıcı bulunamadı!"
            error_banner.visible = True
            txt_username.error_text = "Kullanıcı bulunamadı"
            page.update()

    # Use helper in auth.py so we can test registration programmatically
    from auth import create_user

    def register(e):
        username = txt_username.value
        password = txt_password.value
        if not username or not password:
            register_status.value = "Please enter username and password"
            register_status.color = "#ef4444"
            page.update()
            return

        success, msg = create_user(conn, username, password)
        if success:
            register_status.value = "Account created! Please login."
            register_status.color = "#10b981"
            page.snack_bar = ft.SnackBar(ft.Text("Account created! Please login."))
            page.snack_bar.open = True
        else:
            register_status.value = msg
            register_status.color = "#ef4444"
            page.snack_bar = ft.SnackBar(ft.Text(msg))
            page.snack_bar.open = True
        page.update()

    def logout(e):
        nonlocal current_user
        current_user = None
        app_layout.visible = False
        view_admin.visible = False
        view_login.visible = True
        txt_username.value = ""
        txt_password.value = ""
        # Clear session var
        try:
            with conn.cursor() as cur2:
                cur2.execute("SELECT set_config('app.current_user_id', '', false)")
        except Exception:
            pass
        page.update()

    # --- OYUN MANTIĞI ---
    def start_practice(deck_id):
        nonlocal current_deck_id, current_deck_owner_id
        try:
            current_deck_id = int(deck_id)
        except Exception:
            current_deck_id = deck_id
        with conn.cursor() as cur:
            cur.execute("SELECT owner_id FROM decks WHERE id = %s", (current_deck_id,))
            row = cur.fetchone()
            current_deck_owner_id = row[0] if row else None
        view_manager.visible = False
        practice_view.visible = True
        get_next_card()
        page.update()

    def stop_practice(e):
        view_manager.visible = True
        practice_view.visible = False
        page.update()

    def get_next_card(e=None):
        nonlocal current_card, is_showing_answer

        def can_schedule_reviews():
            if current_deck_owner_id is None:
                return current_user and current_user.get("is_admin")
            if not current_user:
                return False
            return current_user.get("is_admin") or current_user.get("id") == current_deck_owner_id

        with conn.cursor() as cur:
            if can_schedule_reviews():
                cur.execute(
                    """
                    SELECT id, front, back, interval_days, ease_factor, repetitions, next_due
                    FROM cards
                    WHERE deck_id = %s AND COALESCE(next_due, CURRENT_DATE) <= CURRENT_DATE
                    ORDER BY COALESCE(next_due, CURRENT_DATE) ASC, RANDOM()
                    LIMIT 1
                    """,
                    (current_deck_id,)
                )
            else:
                cur.execute(
                    """
                    SELECT id, front, back, interval_days, ease_factor, repetitions, next_due
                    FROM cards
                    WHERE deck_id = %s
                    ORDER BY RANDOM()
                    LIMIT 1
                    """,
                    (current_deck_id,)
                )
            res = cur.fetchone()

            if can_schedule_reviews():
                cur.execute("SELECT COUNT(*) FROM cards WHERE deck_id = %s", (current_deck_id,))
                total_count = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM cards WHERE deck_id = %s AND COALESCE(next_due, CURRENT_DATE) <= CURRENT_DATE",
                    (current_deck_id,)
                )
                due_count = cur.fetchone()[0]
                if total_count == 0:
                    practice_status.value = "No cards in this deck."
                elif due_count == 0:
                    cur.execute(
                        "SELECT MIN(next_due) FROM cards WHERE deck_id = %s",
                        (current_deck_id,)
                    )
                    next_due_date = cur.fetchone()[0]
                    if next_due_date:
                        practice_status.value = f"All caught up. Next due: {next_due_date}"
                    else:
                        practice_status.value = "All caught up."
                else:
                    practice_status.value = f"Due today: {due_count}"
                practice_status.color = "#94a3b8"
            else:
                practice_status.value = "Random mode (shared deck)"
                practice_status.color = "#94a3b8"

        if res:
            current_card = {
                "id": res[0],
                "front": res[1],
                "back": res[2],
                "interval_days": res[3] or 1,
                "ease_factor": float(res[4] or 2.5),
                "repetitions": res[5] or 0,
                "next_due": res[6]
            }
            is_showing_answer = False
            card_text.value = current_card["front"]
            card_container.gradient = ft.LinearGradient(
                begin=ft.Alignment(-1, -1),
                end=ft.Alignment(1, 1),
                colors=["#1e3a8a", "#1e293b"]
            )
            card_container.scale = 1.0
            page.update()
        else:
            current_card = None
            is_showing_answer = False
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM cards WHERE deck_id = %s", (current_deck_id,))
                total_count = cur.fetchone()[0]
            if total_count == 0:
                card_text.value = "No cards in this deck."
            else:
                card_text.value = "No cards due today."
            practice_status.color = "#94a3b8"
            card_container.gradient = ft.LinearGradient(
                begin=ft.Alignment(-1, -1),
                end=ft.Alignment(1, 1),
                colors=["#0f172a", "#1e293b"]
            )
            page.update()

    def flip_card(e):
        nonlocal is_showing_answer
        if current_card:
            is_showing_answer = not is_showing_answer
            card_text.value = current_card["back"] if is_showing_answer else current_card["front"]
            
            if is_showing_answer:
                card_container.gradient = ft.LinearGradient(
                    begin=ft.Alignment(-1, -1),
                    end=ft.Alignment(1, 1),
                    colors=["#0d9488", "#14532d"]
                )
                card_container.scale = 1.05
            else:
                card_container.gradient = ft.LinearGradient(
                    begin=ft.Alignment(-1, -1),
                    end=ft.Alignment(1, 1),
                    colors=["#1e3a8a", "#1e293b"]
                )
                card_container.scale = 1.0
            
            page.update()

    def update_schedule(grade):
        if not current_card:
            return False, "No card selected."

        interval_days = int(current_card["interval_days"])
        ease_factor = float(current_card["ease_factor"])
        repetitions = int(current_card["repetitions"])

        if grade == "again":
            repetitions = 0
            interval_days = 1
        else:
            repetitions += 1
            if repetitions == 1:
                interval_days = 1
            elif repetitions == 2:
                interval_days = 6
            else:
                interval_days = max(1, int(round(interval_days * ease_factor)))

        delta = {
            "again": -0.2,
            "hard": -0.15,
            "good": 0.0,
            "easy": 0.15
        }.get(grade, 0.0)
        ease_factor = max(1.3, ease_factor + delta)

        next_due = date.today() + timedelta(days=interval_days)

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE cards
                    SET interval_days = %s,
                        ease_factor = %s,
                        repetitions = %s,
                        next_due = %s
                    WHERE id = %s
                    """,
                    (interval_days, ease_factor, repetitions, next_due, current_card["id"])
                )
            return True, "Saved"
        except Exception as ex:
            return False, f"Could not update review: {ex}"

    def rate_card(grade):
        if not current_card:
            practice_status.value = "No card to rate."
            practice_status.color = "#fca5a5"
            page.snack_bar = ft.SnackBar(ft.Text("No card to rate."))
            page.snack_bar.open = True
            page.update()
            return
        if not is_showing_answer:
            practice_status.value = "Flip the card to rate."
            practice_status.color = "#fca5a5"
            page.snack_bar = ft.SnackBar(ft.Text("Flip the card to see the answer first."))
            page.snack_bar.open = True
            page.update()
            return

        if current_deck_owner_id is None:
            if not (current_user and current_user.get("is_admin")):
                practice_status.value = "Rating disabled for shared decks."
                practice_status.color = "#fca5a5"
                page.snack_bar = ft.SnackBar(ft.Text("Spaced repetition is disabled for shared decks."))
                page.snack_bar.open = True
                page.update()
                return
        else:
            if not current_user:
                practice_status.value = "Login required to rate cards."
                practice_status.color = "#fca5a5"
                page.snack_bar = ft.SnackBar(ft.Text("Login required to rate cards."))
                page.snack_bar.open = True
                page.update()
                return
            if not (current_user.get("is_admin") or current_user.get("id") == current_deck_owner_id):
                practice_status.value = "You can only rate your own decks."
                practice_status.color = "#fca5a5"
                page.snack_bar = ft.SnackBar(ft.Text("You can only rate cards in your own decks."))
                page.snack_bar.open = True
                page.update()
                return

        ok, msg = update_schedule(grade)
        if not ok:
            practice_status.value = "Could not save rating."
            practice_status.color = "#fca5a5"
            page.snack_bar = ft.SnackBar(ft.Text(msg))
            page.snack_bar.open = True
            page.update()
            return

        get_next_card()

    def add_card_to_deck(e):
        if not current_user:
            page.snack_bar = ft.SnackBar(ft.Text("Please login to add cards."))
            page.snack_bar.open = True
            page.update()
            return

        if txt_front.value and txt_back.value and deck_dropdown.value:
            try:
                deck_id = int(deck_dropdown.value)
            except Exception:
                page.snack_bar = ft.SnackBar(ft.Text("Invalid deck selected"))
                page.snack_bar.open = True
                page.update()
                return

            # Check deck ownership: disallow adding to shared decks or other users' decks
            with conn.cursor() as cur:
                cur.execute("SELECT owner_id FROM decks WHERE id = %s", (deck_id,))
                row = cur.fetchone()
                if not row:
                    page.snack_bar = ft.SnackBar(ft.Text("Selected deck not found."))
                    page.snack_bar.open = True
                    page.update()
                    return
                owner_id = row[0]
                if owner_id is None:
                    page.snack_bar = ft.SnackBar(ft.Text("Cannot add cards to the shared deck."))
                    page.snack_bar.open = True
                    page.update()
                    return
                if owner_id != current_user['id']:
                    page.snack_bar = ft.SnackBar(ft.Text("You can only add cards to your own decks."))
                    page.snack_bar.open = True
                    page.update()
                    return

                cur.execute("INSERT INTO cards (deck_id, front, back) VALUES (%s, %s, %s)", 
                            (deck_id, txt_front.value, txt_back.value))

            txt_front.value = ""
            txt_back.value = ""
            page.snack_bar = ft.SnackBar(ft.Text("Card Saved to Cloud!"))
            page.snack_bar.open = True
            # show confirmation dialog
            show_alert("Card saved", "Card was saved to your deck.")
            load_decks()
            page.update()

    def read_cards_from_csv(file_path):
        with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except Exception:
                dialect = csv.excel
            reader = csv.reader(f, dialect)
            rows = [row for row in reader if row]

        if not rows:
            return [], None

        header = [cell.strip().lower() for cell in rows[0]]
        german_keys = {"german", "deutsch", "front", "question", "term"}
        english_keys = {"english", "englisch", "back", "answer", "definition"}

        has_header = any(h in german_keys for h in header) and any(h in english_keys for h in header)
        if has_header:
            g_idx = next((i for i, h in enumerate(header) if h in german_keys), 0)
            e_idx = next((i for i, h in enumerate(header) if h in english_keys), 1)
            data_rows = rows[1:]
        else:
            g_idx, e_idx = 0, 1
            data_rows = rows

        cards = []
        for row in data_rows:
            if len(row) <= max(g_idx, e_idx):
                continue
            front = row[g_idx].strip()
            back = row[e_idx].strip()
            if front and back:
                cards.append((front, back))

        return cards, has_header

    def import_shared_deck_cards(cards, has_header):
        if not current_user or not current_user.get("is_admin"):
            csv_status.value = "Admin login required to import shared decks."
            csv_status.color = "#fca5a5"
            page.update()
            return

        deck_name = txt_shared_deck_name.value.strip() if txt_shared_deck_name.value else ""
        if not deck_name:
            csv_status.value = "Please enter a shared deck name."
            csv_status.color = "#fca5a5"
            page.update()
            return

        if not cards:
            csv_status.value = "No valid rows found in CSV."
            csv_status.color = "#fca5a5"
            page.update()
            return

        inserted = 0
        skipped = 0
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.current_user_id', %s, false)", (str(current_user["id"]),))
                cur.execute("SELECT id FROM decks WHERE name = %s AND owner_id IS NULL", (deck_name,))
                deck_row = cur.fetchone()
                if deck_row:
                    deck_id = deck_row[0]
                else:
                    cur.execute(
                        "INSERT INTO decks (name, owner_id) VALUES (%s, NULL) RETURNING id",
                        (deck_name,)
                    )
                    deck_id = cur.fetchone()[0]

            for front, back in cards:
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
        except Exception as ex:
            csv_status.value = f"Import failed: {ex}"
            csv_status.color = "#fca5a5"
            page.update()
            return

        header_note = "Header detected" if has_header else "No header detected"
        csv_status.value = f"Imported {inserted}, skipped {skipped}. {header_note}."
        csv_status.color = "#86efac"
        load_decks()
        page.update()

    def import_shared_deck_from_csv(file_path):
        cards, has_header = read_cards_from_csv(file_path)
        import_shared_deck_cards(cards, has_header)

    def create_new_deck(e):
        if not txt_new_deck.value:
            return

        if not current_user:
            page.snack_bar = ft.SnackBar(ft.Text("Please login to create a deck."))
            page.snack_bar.open = True
            page.update()
            return

        with conn.cursor() as cur:
            cur.execute("INSERT INTO decks (name, owner_id) VALUES (%s, %s)", (txt_new_deck.value, current_user['id']))
        txt_new_deck.value = ""
        load_decks()
        show_alert("Deck created", "Your deck was created successfully.")
        page.update()

    def show_delete_user_confirm(user_id, username, is_admin):
        if not current_user or not current_user.get("is_admin"):
            show_alert("Access denied", "Only admins can delete users.")
            return

        if is_admin:
            show_alert("Blocked", "Admin accounts cannot be deleted.")
            return

        if current_user.get("id") == user_id:
            show_alert("Blocked", "You cannot delete your own account.")
            return

        def do_delete(e):
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM decks WHERE owner_id = %s", (user_id,))
                    deck_ids = [row[0] for row in cur.fetchall()]
                    if deck_ids:
                        cur.execute("DELETE FROM cards WHERE deck_id = ANY(%s)", (deck_ids,))
                        cur.execute("DELETE FROM decks WHERE owner_id = %s", (user_id,))
                    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                dlg.open = False
                page.update()
                show_alert("Deleted", f"User '{username}' was deleted.")
                load_admin_data()
                load_decks()
            except Exception as ex:
                dlg.open = False
                page.update()
                show_alert("Error", f"Could not delete user: {ex}")

        def cancel_delete(e):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete user?"),
            content=ft.Text(
                f"This will permanently delete '{username}' and all of their decks/cards. Continue?"
            ),
            actions=[
                ft.TextButton("Cancel", on_click=cancel_delete),
                ft.TextButton("Delete", on_click=do_delete)
            ],
            on_dismiss=lambda e: None
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def load_admin_data():
        admin_user_list.controls.clear()
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, created_at, is_admin FROM users ORDER BY created_at DESC")
            users = cur.fetchall()
            for u in users:
                user_id, username, created_at, is_admin = u
                role = "ADMIN" if is_admin else "User"
                color = "red" if is_admin else "white"
                delete_btn = ft.IconButton(
                    ft.Icons.DELETE,
                    icon_color="#ef4444",
                    tooltip="Delete user",
                    on_click=lambda e, uid=user_id, uname=username, adm=is_admin: show_delete_user_confirm(uid, uname, adm)
                )
                if is_admin or (current_user and current_user.get("id") == user_id):
                    delete_btn.visible = False

                admin_user_list.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Row([
                                ft.Icon(ft.Icons.PERSON, color="white"),
                                ft.Text(f"{username} ({role})", weight="bold", color=color),
                                ft.Text(str(created_at)[:10], size=12, color="grey")
                            ], spacing=10, alignment=ft.MainAxisAlignment.START),
                            delete_btn
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=10, bgcolor="#334155", border_radius=5, margin=2
                    )
                )
        page.update()

    # --- UI EKRANLARI ---
    txt_username = ft.TextField(label="Username", width=300, border_radius=10, on_submit=login)
    txt_password = ft.TextField(label="Password", width=300, password=True, can_reveal_password=True, border_radius=10, on_submit=login)
    register_status = ft.Text("", size=14)
    txt_shared_deck_name = ft.TextField(
        label="Shared Deck Name",
        width=450,
        height=60,
        border_radius=12,
        border_color="#334155",
        focused_border_color="#38bdf8",
        bgcolor="#1e293b",
        text_style=ft.TextStyle(size=15)
    )
    csv_status = ft.Text("", size=12, color="#94a3b8")

    pending_cards = []
    pending_has_header = None

    def show_csv_preview_dialog(card_rows, has_header):
        preview_count = min(5, len(card_rows))
        preview_rows = card_rows[:preview_count]
        header_note = "Header detected" if has_header else "No header detected"

        preview_lines = [f"{i + 1}. {front}  ->  {back}" for i, (front, back) in enumerate(preview_rows)]
        preview_text = "\n".join(preview_lines) if preview_lines else "(No rows)"

        def do_import(e):
            dlg.open = False
            page.update()
            import_shared_deck_cards(card_rows, has_header)

        def cancel_import(e):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("CSV Preview"),
            content=ft.Column([
                ft.Text(f"Rows detected: {len(card_rows)}"),
                ft.Text(header_note, size=12, color="#94a3b8"),
                ft.Text("Preview (first rows):", size=12, color="#94a3b8"),
                ft.Text(preview_text, size=12)
            ], tight=True),
            actions=[
                ft.TextButton("Cancel", on_click=cancel_import),
                ft.TextButton("Import", on_click=do_import)
            ]
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    txt_csv_path = ft.TextField(
        label="CSV File Path",
        width=450,
        height=60,
        border_radius=12,
        border_color="#334155",
        focused_border_color="#38bdf8",
        bgcolor="#1e293b",
        text_style=ft.TextStyle(size=15)
    )

    def import_csv_from_path(e):
        nonlocal pending_cards, pending_has_header
        file_path = txt_csv_path.value.strip() if txt_csv_path.value else ""
        if not file_path:
            csv_status.value = "Please enter a CSV file path."
            csv_status.color = "#fca5a5"
            page.update()
            return
        if not os.path.exists(file_path):
            csv_status.value = "File not found."
            csv_status.color = "#fca5a5"
            page.update()
            return
        cards, has_header = read_cards_from_csv(file_path)
        pending_cards = cards
        pending_has_header = has_header
        if not cards:
            csv_status.value = "No valid rows found in CSV."
            csv_status.color = "#fca5a5"
            page.update()
            return
        show_csv_preview_dialog(pending_cards, pending_has_header)
    
    # ERROR BANNER - GÖMÜLü, GARANTILI GÖRÜNÜR
    error_banner = ft.Container(
        content=ft.Text("", size=16, weight="bold", color="white", text_align="center"),
        bgcolor="#dc2626",
        padding=15,
        border_radius=10,
        margin=ft.Margin(bottom=15),
        visible=False
    )
    
    view_login = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.CLOUD_QUEUE, size=60, color="#2563eb"),
            ft.Text("CLOUD FLASHCARDS", size=24, weight="bold"),
            ft.Container(height=20),
            error_banner,
            txt_username, txt_password,
            register_status,
            ft.Container(height=20),
            ft.Row([
                ft.Button("LOGIN", on_click=login, width=140, height=50, bgcolor="#2563eb"),
                ft.Button("REGISTER", on_click=register, width=140, height=50, bgcolor="#475569")
            ], alignment=ft.MainAxisAlignment.CENTER)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER, expand=True, visible=True
    )

    # 2. DECKS & APP
    txt_new_deck = ft.TextField(
        label="New Deck Name",
        expand=True,
        height=50,
        border_radius=10,
        border_color="#334155",
        focused_border_color="#3b82f6",
        bgcolor="#1e293b",
        text_style=ft.TextStyle(size=14)
    )
    
    # Debug info panel (can be removed in production)
    debug_info = ft.Container(
        content=ft.Column([
            ft.Text("", size=10, color="#64748b")  # Will be updated with user/admin info
        ]),
        bgcolor="#1e293b",
        padding=8,
        border_radius=8,
        margin=ft.Margin(bottom=10, left=0, right=0, top=0),
        visible=False,
        border=ft.Border.all(1, "#334155")
    )
    
    def update_debug_info():
        if current_user:
            debug_text = f"👤 {current_user['username']} | {'👑 Admin' if current_user['is_admin'] else '👤 User'}"
            debug_info.content.controls[0].value = debug_text
            debug_info.visible = True
        else:
            debug_info.visible = False
        page.update()
    
    view_decks = ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.LAYERS_ROUNDED, color="#3b82f6", size=28),
                        ft.Text("YOUR DECKS", size=26, weight="bold", color="#f1f5f9")
                    ], spacing=10),
                ),
                ft.IconButton(
                    ft.Icons.LOGOUT,
                    icon_color="#ef4444",
                    icon_size=24,
                    on_click=logout,
                    tooltip="Logout"
                )
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            margin=ft.Margin(bottom=15, left=0, right=0, top=0)
        ),
        debug_info,
        ft.Container(
            content=ft.Row([
                txt_new_deck,
                ft.Container(
                    content=ft.Icon(ft.Icons.ADD_CIRCLE, color="white", size=24),
                    bgcolor="#3b82f6",
                    border_radius=10,
                    padding=8,
                    on_click=create_new_deck,
                    ink=True,
                    tooltip="Create New Deck",
                    animate=ft.Animation(200, "easeOut")
                )
            ], spacing=10),
            margin=ft.Margin(bottom=20, left=0, right=0, top=0)
        ),
        ft.Divider(color="#334155", height=1),
        ft.Container(height=10),
        ft.Row([
            ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.PUBLIC, color="#60a5fa", size=20),
                        ft.Text("Shared / Other Decks", size=16, weight="bold", color="#94a3b8")
                    ], spacing=8),
                    margin=ft.Margin(bottom=15, left=0, right=0, top=0)
                ),
                ft.Container(content=shared_decks_list, expand=True)
            ], expand=True),
            ft.Container(width=20),
            ft.Container(
                width=340,
                content=ft.Column([
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.PERSON, color="#a855f7", size=20),
                            ft.Text("My Decks", size=16, weight="bold", color="#94a3b8")
                        ], spacing=8),
                        margin=ft.Margin(bottom=15, left=0, right=0, top=0)
                    ),
                    ft.Container(content=my_decks_list, expand=True)
                ], expand=True)
            )
        ], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START, expand=True)
    ], visible=True, expand=True)

    txt_front = ft.TextField(
        label="Front (German)",
        width=450,
        height=60,
        border_radius=12,
        border_color="#334155",
        focused_border_color="#3b82f6",
        bgcolor="#1e293b",
        text_style=ft.TextStyle(size=15)
    )
    txt_back = ft.TextField(
        label="Back (English)",
        width=450,
        height=60,
        border_radius=12,
        border_color="#334155",
        focused_border_color="#10b981",
        bgcolor="#1e293b",
        text_style=ft.TextStyle(size=15)
    )
    view_browser = ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.ADD_CARD, color="#3b82f6", size=32),
                ft.Text("ADD NEW CARD", size=26, weight="bold", color="#f1f5f9")
            ], spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            margin=ft.Margin(bottom=30, left=0, right=0, top=0)
        ),
        ft.Container(
            content=deck_dropdown,
            bgcolor="#1e293b",
            padding=15,
            border_radius=12,
            border=ft.Border.all(1, "#334155"),
            margin=ft.Margin(bottom=20, left=0, right=0, top=0)
        ),
        ft.Container(
            content=txt_front,
            margin=ft.Margin(bottom=15, left=0, right=0, top=0)
        ),
        ft.Container(
            content=txt_back,
            margin=ft.Margin(bottom=30, left=0, right=0, top=0)
        ),
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CLOUD_UPLOAD, color="white", size=22),
                ft.Text("SAVE TO CLOUD", size=16, weight="bold", color="white")
            ], spacing=10, alignment=ft.MainAxisAlignment.CENTER),
            bgcolor="#3b82f6",
            padding=ft.Padding(left=40, right=40, top=18, bottom=18),
            border_radius=12,
            on_click=add_card_to_deck,
            ink=True,
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=15,
                color="#3b82f666",
                offset=ft.Offset(0, 5)
            ),
            animate=ft.Animation(200, "easeOut")
        ),
        ft.Container(height=25),
        ft.Divider(color="#334155", height=1),
        ft.Container(height=15),
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.UPLOAD_FILE, color="#38bdf8", size=28),
                ft.Text("IMPORT SHARED DECK (ADMIN)", size=20, weight="bold", color="#f1f5f9")
            ], spacing=10, alignment=ft.MainAxisAlignment.CENTER),
            margin=ft.Margin(bottom=20, left=0, right=0, top=0)
        ),
        ft.Container(
            content=txt_shared_deck_name,
            margin=ft.Margin(bottom=15, left=0, right=0, top=0)
        ),
        ft.Container(
            content=txt_csv_path,
            margin=ft.Margin(bottom=10, left=0, right=0, top=0)
        ),
        ft.Container(
            content=ft.Text(
                "CSV columns: German, English (header optional). If no header, first two columns are used.",
                size=12,
                color="#94a3b8",
                text_align="center"
            ),
            margin=ft.Margin(bottom=10, left=0, right=0, top=0)
        ),
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.CLOUD_UPLOAD, color="white", size=20),
                ft.Text("IMPORT CSV", size=14, weight="bold", color="white")
            ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
            bgcolor="#0ea5e9",
            padding=ft.Padding(left=30, right=30, top=14, bottom=14),
            border_radius=12,
            on_click=import_csv_from_path,
            ink=True,
            shadow=ft.BoxShadow(
                spread_radius=1,
                blur_radius=10,
                color="#0ea5e966",
                offset=ft.Offset(0, 4)
            ),
            animate=ft.Animation(200, "easeOut")
        ),
        ft.Container(height=10),
        csv_status
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, visible=False)

    # 3. GAME
    card_text = ft.Text("Ready?", size=40, weight="bold", text_align="center")
    practice_status = ft.Text("", size=14, color="#94a3b8")
    card_container = ft.Container(
        content=card_text,
        width=550,
        height=380,
        gradient=ft.LinearGradient(
            begin=ft.Alignment(-1, -1),
            end=ft.Alignment(1, 1),
            colors=["#1e3a8a", "#1e293b"]
        ),
        border_radius=25,
        alignment=ft.Alignment(0, 0),
        on_click=flip_card,
        animate=ft.Animation(400, "easeOut"),
        shadow=ft.BoxShadow(
            spread_radius=2,
            blur_radius=30,
            color="#00000080",
            offset=ft.Offset(0, 10)
        ),
        border=ft.Border.all(2, "#334155")
    )

    def make_rating_button(label, color, grade):
        return ft.Container(
            content=ft.Text(label, size=14, weight="bold", color="white"),
            bgcolor=color,
            padding=ft.Padding(left=16, right=16, top=10, bottom=10),
            border_radius=10,
            on_click=lambda e, g=grade: rate_card(g),
            ink=True,
            animate=ft.Animation(150, "easeOut")
        )

    rating_row = ft.Row(
        [
            make_rating_button("Again", "#ef4444", "again"),
            make_rating_button("Hard", "#f59e0b", "hard"),
            make_rating_button("Good", "#10b981", "good"),
            make_rating_button("Easy", "#3b82f6", "easy")
        ],
        spacing=12,
        alignment=ft.MainAxisAlignment.CENTER
    )
    practice_view = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.ARROW_BACK, color="white", size=24),
                    bgcolor="#334155",
                    border_radius=10,
                    padding=10,
                    on_click=stop_practice,
                    ink=True,
                    tooltip="Back to Decks"
                ),
                ft.Text("Practice Mode", size=22, weight="bold", color="#f1f5f9")
            ], spacing=15),
            ft.Container(height=30),
            card_container,
            ft.Container(height=12),
            practice_status,
            ft.Container(height=40),
            rating_row,
            ft.Container(height=24),
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.SKIP_NEXT, color="white", size=20),
                    ft.Text("NEXT CARD", size=15, weight="bold", color="white")
                ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
                bgcolor="#0d9488",
                padding=ft.Padding(left=30, right=30, top=15, bottom=15),
                border_radius=12,
                on_click=get_next_card,
                ink=True,
                shadow=ft.BoxShadow(
                    spread_radius=1,
                    blur_radius=10,
                    color="#0d948866",
                    offset=ft.Offset(0, 4)
                ),
                animate=ft.Animation(200, "easeOut")
            )
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        visible=False,
        bgcolor="#0f172a",
        expand=True,
        alignment=ft.Alignment.CENTER,
        padding=30
    )

    # 4. ADMIN
    view_admin = ft.Container(
        content=ft.Column([
            ft.Row([ft.Text("ADMIN PANEL", size=24, weight="bold", color="red"), ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: switch_tab(0))]),
            ft.Divider(),
            ft.Text("Registered Users:", size=16),
            admin_user_list
        ]), padding=20, visible=False, bgcolor="#0f172a", expand=True
    )

    # --- NAVIGATION ---
    def switch_tab(index):
        if index == 3:
            app_layout.visible = False
            view_admin.visible = True
            load_admin_data()
        else:
            app_layout.visible = True
            view_admin.visible = False
            view_decks.visible = (index == 0)
            view_browser.visible = (index == 1)
            if index == 0: load_decks()
            if index == 1: load_decks()
        page.update()

    btn_admin_panel = ft.IconButton(
        ft.Icons.ADMIN_PANEL_SETTINGS,
        icon_color="#ef4444",
        icon_size=28,
        visible=False,
        on_click=lambda e: switch_tab(3),
        tooltip="Admin Panel"
    )
    
    bottom_nav = ft.Container(
        content=ft.Row([
            ft.Container(
                content=ft.Icon(ft.Icons.LAYERS, color="#60a5fa", size=28),
                padding=10,
                border_radius=10,
                on_click=lambda _: switch_tab(0),
                tooltip="Decks",
                ink=True,
                animate=ft.Animation(200, "easeOut")
            ),
            ft.Container(
                content=ft.Icon(ft.Icons.ADD_CIRCLE, color="#10b981", size=28),
                padding=10,
                border_radius=10,
                on_click=lambda _: switch_tab(1),
                tooltip="Add Card",
                ink=True,
                animate=ft.Animation(200, "easeOut")
            ),
            btn_admin_panel
        ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
        bgcolor="#1e293b",
        padding=15,
        border_radius=ft.BorderRadius.only(top_left=20, top_right=20),
        shadow=ft.BoxShadow(
            spread_radius=1,
            blur_radius=20,
            color="#00000080",
            offset=ft.Offset(0, -5)
        )
    )

    view_manager = ft.Container(content=ft.Column([view_decks, view_browser]), padding=20, expand=True)
    app_layout = ft.Column([view_manager, bottom_nav], expand=True, visible=False)

    page.add(ft.Stack([view_login, app_layout, view_admin, practice_view], expand=True))

if __name__ == "__main__":
    # When deployed to Render (or other PaaS) the platform provides a PORT
    # environment variable and requires binding to 0.0.0.0 so external
    # clients can reach the server. Use that when available; otherwise
    # fall back to ft.run() for local development.
    try:
        port = int(os.environ.get("PORT", 0))
    except Exception:
        port = 0

    if port:
        # Start Flet app listening on all interfaces on the provided port.
        # ft.app provides a simple way to specify host/port for deployments.
        try:
            ft.app(target=main, host="0.0.0.0", port=port)
        except Exception:
            # If ft.app is not available in this flet version, fall back.
            ft.run(main)
    else:
        ft.run(main)
