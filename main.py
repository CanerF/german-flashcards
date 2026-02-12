import flet as ft
import psycopg2
import bcrypt
import os
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id SERIAL PRIMARY KEY,
                deck_id INTEGER REFERENCES decks(id),
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                level INTEGER DEFAULT 0
            );
        """)

        # Admin Kullanıcısı
        cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
        if cursor.fetchone()[0] == 0:
            # Create admin user only if INITIAL_ADMIN_PASSWORD is provided in environment
            initial_admin_pw = os.getenv("INITIAL_ADMIN_PASSWORD")
            if initial_admin_pw:
                hashed_pw = bcrypt.hashpw(initial_admin_pw.encode('utf-8'), bcrypt.gensalt())
                cursor.execute(
                    "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s)", 
                    ('admin', hashed_pw.decode('utf-8'), True)
                )
                print("👤 Admin user created (user: admin)")
            else:
                print("⚠️ INITIAL_ADMIN_PASSWORD not set — admin user not created automatically.")

        # Standart Deste
        cursor.execute("SELECT id FROM decks WHERE name = 'Standard German Start'")
        if not cursor.fetchone():
            print("📚 Creating Standard Deck on Cloud...")
            cursor.execute("INSERT INTO decks (name) VALUES ('Standard German Start') RETURNING id")
            std_deck_id = cursor.fetchone()[0]
            
            initial_words = [
                ("Der Hund", "The Dog"), ("Die Katze", "The Cat"), ("Das Brot", "The Bread"),
                ("Das Wasser", "The Water"), ("Hallo", "Hello"), ("Tschüss", "Goodbye"),
                ("Danke", "Thank you"), ("Bitte", "Please")
            ]
            for front, back in initial_words:
                cursor.execute("INSERT INTO cards (deck_id, front, back) VALUES (%s, %s, %s)", (std_deck_id, front, back))

    # --- STATE ---
    current_user = None 
    current_deck_id = None 
    current_card = None
    is_showing_answer = False

    # --- UI REFERANSLARI ---
    decks_list = ft.Column(scroll=ft.ScrollMode.AUTO)
    deck_dropdown = ft.Dropdown(label="Select Deck", width=300)
    admin_user_list = ft.Column(scroll=ft.ScrollMode.AUTO)

    # --- DATA FONKSİYONLARI ---
    def load_decks():
        decks_list.controls.clear()
        options = []
        with conn.cursor() as cur:
            cur.execute("""
                SELECT d.id, d.name, COUNT(c.id) 
                FROM decks d 
                LEFT JOIN cards c ON d.id = c.deck_id 
                GROUP BY d.id, d.name ORDER BY d.id
            """)
            rows = cur.fetchall()
            for deck_id, name, count in rows:
                options.append(ft.dropdown.Option(key=str(deck_id), text=name))
                decks_list.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(name, size=18, weight="bold"),
                                ft.Text(f"{count} Cards", size=12, color="grey")
                            ]),
                            ft.Button(
                                content=ft.Text("PLAY"),
                                on_click=lambda e, did=deck_id: start_practice(did),
                                bgcolor="#0d9488", height=40
                            )
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        bgcolor="#1e293b", padding=15, border_radius=10,
                        margin=ft.margin.only(bottom=10)
                    )
                )
        deck_dropdown.options = options
        if options: deck_dropdown.value = options[0].key
        page.update()

    # --- AUTH FONKSİYONLARI ---
    def login(e):
        nonlocal current_user
        username = txt_username.value
        password = txt_password.value

        with conn.cursor() as cur:
            cur.execute("SELECT id, username, password_hash, is_admin FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
        
        if user:
            stored_hash = user[2].encode('utf-8')
            if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
                current_user = {"id": user[0], "username": user[1], "is_admin": user[3]}
                page.snack_bar = ft.SnackBar(ft.Text(f"Welcome, {current_user['username']}!"))
                page.snack_bar.open = True
                
                view_login.visible = False
                app_layout.visible = True
                if current_user['is_admin']:
                    btn_admin_panel.visible = True
                else:
                    btn_admin_panel.visible = False
                load_decks()
                page.update()
            else:
                txt_password.error_text = "Wrong password"
                page.update()
        else:
            txt_username.error_text = "User not found"
            page.update()

    def register(e):
        username = txt_username.value
        password = txt_password.value
        if not username or not password: return

        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (username, password_hash) VALUES (%s, %s)", (username, hashed_pw.decode('utf-8')))
            page.snack_bar = ft.SnackBar(ft.Text("Account created! Please login."))
            page.snack_bar.open = True
            page.update()
        except Exception:
            page.snack_bar = ft.SnackBar(ft.Text("Username already taken!"))
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
        page.update()

    # --- OYUN MANTIĞI ---
    def start_practice(deck_id):
        nonlocal current_deck_id
        current_deck_id = deck_id
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
        with conn.cursor() as cur:
            cur.execute("SELECT front, back FROM cards WHERE deck_id = %s ORDER BY RANDOM() LIMIT 1", (current_deck_id,))
            res = cur.fetchone()
        
        if res:
            current_card = res
            is_showing_answer = False
            card_text.value = current_card[0]
            card_container.bgcolor = "#1e293b"
            card_container.scale = 1.0
            page.update()
        else:
            card_text.value = "No cards!"
            page.update()

    def flip_card(e):
        nonlocal is_showing_answer
        if current_card:
            is_showing_answer = not is_showing_answer
            card_text.value = current_card[1] if is_showing_answer else current_card[0]
            card_container.bgcolor = "#0d9488" if is_showing_answer else "#1e293b"
            page.update()

    def add_card_to_deck(e):
        if txt_front.value and txt_back.value and deck_dropdown.value:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO cards (deck_id, front, back) VALUES (%s, %s, %s)", 
                            (deck_dropdown.value, txt_front.value, txt_back.value))
            txt_front.value = ""
            txt_back.value = ""
            page.snack_bar = ft.SnackBar(ft.Text("Card Saved to Cloud!"))
            page.snack_bar.open = True
            load_decks()
            page.update()

    def create_new_deck(e):
        if txt_new_deck.value:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO decks (name) VALUES (%s)", (txt_new_deck.value,))
            txt_new_deck.value = ""
            load_decks()
            page.update()

    def load_admin_data():
        admin_user_list.controls.clear()
        with conn.cursor() as cur:
            cur.execute("SELECT username, created_at, is_admin FROM users ORDER BY created_at DESC")
            users = cur.fetchall()
            for u in users:
                role = "ADMIN" if u[2] else "User"
                color = "red" if u[2] else "white"
                admin_user_list.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.PERSON, color="white"),
                            ft.Text(f"{u[0]} ({role})", weight="bold", color=color),
                            ft.Text(str(u[1])[:10], size=12, color="grey")
                        ]),
                        padding=10, bgcolor="#334155", border_radius=5, margin=2
                    )
                )
        page.update()

    # --- UI EKRANLARI ---
    # 1. LOGIN
    txt_username = ft.TextField(label="Username", width=300, border_radius=10)
    txt_password = ft.TextField(label="Password", width=300, password=True, can_reveal_password=True, border_radius=10)
    
    view_login = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.CLOUD_QUEUE, size=60, color="#2563eb"),
            ft.Text("CLOUD FLASHCARDS", size=24, weight="bold"),
            ft.Container(height=20),
            txt_username, txt_password,
            ft.Container(height=20),
            ft.Row([
                ft.Button("LOGIN", on_click=login, width=140, height=50, bgcolor="#2563eb"),
                ft.Button("REGISTER", on_click=register, width=140, height=50, bgcolor="#475569")
            ], alignment=ft.MainAxisAlignment.CENTER)
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER),
        alignment=ft.Alignment.CENTER, expand=True, visible=True
    )

    # 2. DECKS & APP
    txt_new_deck = ft.TextField(label="New Deck Name", expand=True, height=40)
    view_decks = ft.Column([
        ft.Row([ft.Text("YOUR DECKS", size=24, weight="bold"), ft.IconButton(ft.Icons.LOGOUT, on_click=logout)]),
        ft.Row([txt_new_deck, ft.IconButton(ft.Icons.ADD, bgcolor="#2563eb", on_click=create_new_deck)]),
        ft.Divider(),
        decks_list
    ], visible=True)

    txt_front = ft.TextField(label="Front (German)", width=400)
    txt_back = ft.TextField(label="Back (English)", width=400)
    view_browser = ft.Column([
        ft.Text("ADD CARD", size=24, weight="bold"),
        ft.Container(height=20),
        deck_dropdown, txt_front, txt_back,
        ft.Container(height=20),
        ft.Button("SAVE TO CLOUD", on_click=add_card_to_deck, bgcolor="#2563eb", width=200, height=50)
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, visible=False)

    # 3. GAME
    card_text = ft.Text("Ready?", size=40, weight="bold", text_align="center")
    card_container = ft.Container(
        content=card_text, width=500, height=350, bgcolor="#1e293b", border_radius=20,
        alignment=ft.Alignment(0, 0), on_click=flip_card, animate=ft.Animation(300, "easeOut"),
        shadow=ft.BoxShadow(blur_radius=50, color="#00000080")
    )
    practice_view = ft.Container(
        content=ft.Column([
            ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=stop_practice), ft.Text("Practice Mode", size=20)]),
            ft.Container(height=20), card_container, ft.Container(height=30),
            ft.Button("NEXT CARD", on_click=get_next_card, bgcolor="#0d9488")
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        visible=False, bgcolor="#0f172a", expand=True, alignment=ft.Alignment.CENTER
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

    btn_admin_panel = ft.IconButton(ft.Icons.ADMIN_PANEL_SETTINGS, icon_color="red", visible=False, on_click=lambda e: switch_tab(3))
    
    bottom_nav = ft.Container(
        content=ft.Row([
            ft.IconButton(ft.Icons.LAYERS, on_click=lambda _: switch_tab(0), tooltip="Decks"),
            ft.IconButton(ft.Icons.ADD_CIRCLE, on_click=lambda _: switch_tab(1), tooltip="Add"),
            btn_admin_panel
        ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
        bgcolor="#1e293b", padding=10, border_radius=ft.BorderRadius.only(top_left=15, top_right=15)
    )

    view_manager = ft.Container(content=ft.Column([view_decks, view_browser]), padding=20, expand=True)
    app_layout = ft.Column([view_manager, bottom_nav], expand=True, visible=False)

    page.add(ft.Stack([view_login, app_layout, view_admin, practice_view], expand=True))

ft.run(main)