import os
import json
import base64
from dotenv import load_dotenv
from cryptography.fernet import Fernet
import asyncio
from datetime import datetime, timedelta
import pytz
import shutil
import random
import string
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    MessageHandler, filters, ConversationHandler
)

def generate_random_accesscode(length=8):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
    print(f"[ACCESS CODE] Generated random access code: {code}")
    return code


from workers import (
    manual_unlock,
    start_auto_unlock_for_user,
    stop_auto_unlock,
    is_auto_unlock_running,
    test_tokens,
)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ACCESS_CODE = os.getenv("ACCESS_CODE")

if ACCESS_CODE== "RANDOM":
    ACCESS_CODE = generate_random_accesscode()
if not BOT_TOKEN or not ACCESS_CODE:
    print("Set BOT_TOKEN and ACCESS_CODE in your .env file!")
    exit(1)



def get_encryption_key():
    while True:
        key_b64 = input("Enter the encryption key (base64, 32 bytes after decoding):  ").strip()
        try:
            key = base64.urlsafe_b64decode(key_b64)
            if len(key) != 32:
                print("Error: the key must be 32 bytes after base64 decoding.")
                continue
            return base64.urlsafe_b64encode(key)
        except Exception:
            print("Base64 decoding error, please try again.")

FERNET_KEY = get_encryption_key()
fernet = Fernet(FERNET_KEY)

# Conversation states for /setup
SETUP_LOGIN, SETUP_PASSWORD = range(2)

def user_dir_path(user_id):
    return os.path.join(DATA_DIR, f"{user_id}")

def is_user_authorized(user_id):
    return os.path.isdir(user_dir_path(user_id))

def create_user_folder(user_id):
    path = user_dir_path(user_id)
    os.makedirs(path, exist_ok=True)

def credentials_path(user_id):
    return os.path.join(user_dir_path(user_id), "credentials.json")

def save_credentials(user_id, login_encrypted, password_encrypted):
    data = {
        "email": login_encrypted.decode(),
        "password": password_encrypted.decode()
    }
    with open(credentials_path(user_id), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def load_credentials(user_id):
    try:
        with open(credentials_path(user_id), "r", encoding="utf-8") as f:
            data = json.load(f)
            login_encrypted = data.get("email", "").encode()
            pwd_encrypted = data.get("password", "").encode()
            login = fernet.decrypt(login_encrypted).decode()
            password = fernet.decrypt(pwd_encrypted).decode()
            return {
                "email": login,
                "password": password
            }
    except Exception:
        return None

def language_is_english(update: Update):
    lang = update.effective_user.language_code
    return lang is not None and lang.startswith("en")

async def send_text(update: Update, text_pl, text_en):
    if language_is_english(update):
        await update.message.reply_text(text_en)
    else:
        await update.message.reply_text(text_pl)

# --- /start ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_authorized(user_id):
        await send_text(update,
            "Jesteś już autoryzowany. Użyj /help, aby zobaczyć dostępne komendy.",
            "You are already authorized. Use /help to see available commands."
        )
    else:
        await send_text(update,
            "Nie jesteś autoryzowany. Podaj kod dostępu komendą:\n/accesscode <kod>",
            "You are not authorized. Please provide access code using:\n/accesscode <code>"
        )

# --- /accesscode ---
async def accesscode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) != 1:
        await send_text(update,
            "Użyj /accesscode <kod>",
            "Use /accesscode <code>"
        )
        return

    code = args[0]
    if code == ACCESS_CODE:
        create_user_folder(user_id)
        await send_text(update,
            "Kod poprawny, masz dostęp do dalszych komend.",
            "Access code accepted, you can use other commands now."
        )
    else:
        await send_text(update,
            "Niepoprawny kod dostępu.",
            "Wrong access code."
        )

# --- /setup ---
async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_user_authorized(user_id):
        await send_text(update,
            "Najpierw autoryzuj się komendą /accesscode <kod>",
            "Please authorize first using /accesscode <code>"
        )
        return ConversationHandler.END

    await send_text(update,
        "Podaj Xiaomi ID (email lub numer telefonu):",
        "Please enter Xiaomi ID (email or phone number):"
    )
    return SETUP_LOGIN

async def setup_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login = update.message.text.strip()
    context.user_data['setup_login'] = login

    await send_text(update,
        "Podaj hasło:",
        "Please enter your password:"
    )
    try:
        await update.message.delete()
    except:
        pass

    return SETUP_PASSWORD

async def setup_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    login = context.user_data.get('setup_login')
    user_id = update.effective_user.id

    login_encrypted = fernet.encrypt(login.encode())
    password_encrypted = fernet.encrypt(password.encode())
    save_credentials(user_id, login_encrypted, password_encrypted)
    try:
        await update.message.delete()
    except:
        pass

    await send_text(update,
        "Dane zapisane pomyślnie.",
        "Data saved successfully."
    )
    return ConversationHandler.END

async def setup_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_text(update,
        "Anulowano ustawienia.",
        "Setup cancelled."
    )
    return ConversationHandler.END

# --- /manual_unlock ---
async def manual_unlock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_user_authorized(user_id):
        await send_text(update,
            "Najpierw autoryzuj się komendą /accesscode <kod>",
            "Please authorize first using /accesscode <code>"
        )
        return

    user_data = load_credentials(user_id)
    if not user_data:
        await send_text(update,
            "Brak zapisanych danych. Użyj /setup aby je wprowadzić.",
            "No saved credentials found. Use /setup to configure."
        )
        return

    await send_text(update,
        "Rozpoczynam manualny proces odblokowania...",
        "Starting manual unlock process..."
    )

    await manual_unlock(user_id, user_data, context.bot)

    await send_text(update,
        "Proces manualnego odblokowania zakończony.",
        "Manual unlock process finished."
    )

# --- /auto_unlock_start ---
async def auto_unlock_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_user_authorized(user_id):
        await send_text(update,
            "Najpierw autoryzuj się komendą /accesscode <kod>",
            "Please authorize first using /accesscode <code>"
        )
        return

    user_data = load_credentials(user_id)
    if not user_data:
        await send_text(update,
            "Brak zapisanych danych. Użyj /setup aby je wprowadzić.",
            "No saved credentials found. Use /setup to configure."
        )
        return

    if is_auto_unlock_running(user_id):
        await send_text(update,
            "Auto unlock już działa.",
            "Auto unlock is already running."
        )
        return

    # Zapisujemy status
    status_path = os.path.join(user_dir_path(user_id), "status")
    with open(status_path, "w", encoding="utf-8") as f:
        f.write("autounlock")

    tz_china = "Asia/Shanghai"
    from datetime import datetime, timezone
    import pytz
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    now_china = now_utc.astimezone(pytz.timezone(tz_china))
    midnight_china = now_china.replace(hour=0, minute=0, second=0, microsecond=0)
    if now_china >= midnight_china:
        from datetime import timedelta
        midnight_china += timedelta(days=1)

    seconds_left = (midnight_china - now_china).total_seconds()
    hours_left = int(seconds_left // 3600)
    minutes_left = int((seconds_left % 3600) // 60)

    await send_text(update,
        f"Uruchamiam auto unlock (czekam na 00:00 czasu chińskiego)...\nDo czasu pozostało: {hours_left} godzin i {minutes_left} minut.",
        f"Starting auto unlock (waiting for 00:00 China time)...\nTime left: {hours_left} hours and {minutes_left} minutes."
    )

    await start_auto_unlock_for_user(user_id, user_data, context.bot)

# --- /auto_unlock_stop ---
async def auto_unlock_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_user_authorized(user_id):
        await send_text(update,
            "Najpierw autoryzuj się komendą /accesscode <kod>",
            "Please authorize first using /accesscode <code>"
        )
        return

    if not is_auto_unlock_running(user_id):
        await send_text(update,
            "Auto unlock nie jest uruchomiony.",
            "Auto unlock is not running."
        )
        return

    stop_auto_unlock(user_id)

    # Usuwamy status
    status_path = os.path.join(user_dir_path(user_id), "status")
    if os.path.exists(status_path):
        os.remove(status_path)

    await send_text(update,
        "Auto unlock zatrzymany.",
        "Auto unlock stopped."
    )

# --- /test ---
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_user_authorized(user_id):
        await send_text(update,
            "Najpierw autoryzuj się komendą /accesscode <kod>",
            "Please authorize first using /accesscode <code>"
        )
        return

    user_data = load_credentials(user_id)
    if not user_data:
        await send_text(update,
            "Brak zapisanych danych logowania. Użyj /setup aby je wprowadzić.",
            "No saved login data found. Use /setup to configure."
        )
        return

    await send_text(update,
        "Testuję połączenie i pobieram tokeny...",
        "Testing connection and fetching tokens..."
    )

    tokens = await test_tokens(user_id, user_data)
    if not tokens:
        await send_text(update,
            "Nie udało się pobrać tokenów. Sprawdź swoje dane i spróbuj ponownie.\nFailed to fetch tokens. Check your credentials and try again.",
            "Failed to fetch tokens. Check your credentials and try again."
        )
        return

    msg = (
        f"Tokeny pobrane pomyślnie:\n\n"
        f"new_bbs_serviceToken: {tokens.get('new_bbs_serviceToken', 'Brak')}\n"
        f"popRunToken: {tokens.get('popRunToken', 'Brak')}\n\n"
        f"Tokens fetched successfully:\n\n"
        f"new_bbs_serviceToken: {tokens.get('new_bbs_serviceToken', 'Missing')}\n"
        f"popRunToken: {tokens.get('popRunToken', 'Missing')}"
    )
    await update.message.reply_text(msg)

#Usuwanie danych
async def clear_user_data(user_id):
    if is_auto_unlock_running(user_id):
        stop_auto_unlock(user_id)

    path = user_dir_path(user_id)
    if os.path.exists(path) and os.path.isdir(path):
        try:
            shutil.rmtree(path)
            print(f"Usunięto folder użytkownika {user_id}: {path}")
            return True
        except Exception as e:
            print(f"Błąd przy usuwaniu folderu {path}: {e}")
            return False
    else:
        print(f"Folder użytkownika {user_id} nie istnieje: {path}")
    return False

async def clear_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_user_authorized(user_id):
        await send_text(update,
            "Nie jesteś autoryzowany.",
            "You are not authorized."
        )
        return

    success = await clear_user_data(user_id)
    if success:
        await send_text(update,
            "Twoje dane zostały usunięte. Auto unlock zatrzymany jeśli był aktywny.",
            "Your data has been deleted. Auto unlock stopped if it was active."
        )
    else:
        await send_text(update,
            "Nie znaleziono Twoich danych do usunięcia.",
            "No data found to delete."
        )


# --- /help ---
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_text(update,
        "/start - rozpocznij\n"
        "/accesscode <kod> - podaj kod dostępu\n"
        "/setup - skonfiguruj login i hasło (interaktywnie)\n"
        "/manual_unlock - rozpocznij proces odblokowania manualnie\n"
        "/auto_unlock_start - uruchom auto unlock\n"
        "/auto_unlock_stop - zatrzymaj auto unlock\n"
        "/test - przetestuj pobieranie tokenów\n"
        "/clear_data - usuń wszystkie Twoje dane i zatrzymaj auto unlock\n"
        "/help - pomoc\n"
        "/cancel - anuluj aktualną operację (np. /setup)",
        "/start - start\n"
        "/accesscode <code> - enter access code\n"
        "/setup - configure login and password (interactive)\n"
        "/manual_unlock - start manual unlock process\n"
        "/auto_unlock_start - start auto unlock\n"
        "/auto_unlock_stop - stop auto unlock\n"
        "/test - test fetching tokens\n"
        "/clear_data - delete all your data and stop auto unlock\n"
        "/help - help\n"
        "/cancel - cancel current operation (e.g. /setup)"
    )

# --- /cancel ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_text(update,
        "Anulowano.",
        "Cancelled."
    )
    return ConversationHandler.END

# --- unknown command ---
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_text(update,
        "Nieznana komenda. Użyj /help.",
        "Unknown command. Use /help."
    )

# --- Resume auto unlocks after restart ---
async def resume_all_auto_unlocks(app):
    tz_china = pytz.timezone('Asia/Shanghai')
    now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
    now_china = now_utc.astimezone(tz_china)
    midnight_china = now_china.replace(hour=0, minute=0, second=0, microsecond=0)
    if now_china >= midnight_china:
        midnight_china += timedelta(days=1)

    time_delta = midnight_china - now_china
    total_seconds = int(time_delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    time_str = f"{hours} godz. {minutes} min. {seconds} sek."
    time_str_en = f"{hours}h {minutes}m {seconds}s"

    for user_id_str in os.listdir(DATA_DIR):
        if not user_id_str.isdigit():
            continue
        user_id = int(user_id_str)
        user_data = load_credentials(user_id)
        if not user_data:
            continue
        status_path = os.path.join(user_dir_path(user_id), "status")
        if os.path.exists(status_path):
            with open(status_path, "r", encoding="utf-8") as f:
                status = f.read().strip()
            if status == "autounlock":
                from workers import is_auto_unlock_running, start_auto_unlock_for_user
                if not is_auto_unlock_running(user_id):
                    print(f"Wznawiam auto unlock dla user {user_id}")
                    await start_auto_unlock_for_user(user_id, user_data, app.bot)

                    # Pobierz info o użytkowniku z Telegrama
                    try:
                        user = await app.bot.get_chat(user_id)
                        lang = user.language_code or "pl"
                    except Exception:
                        lang = "pl"  # domyślnie polski jeśli błąd

                    if lang.startswith("en"):
                        message = (
                            f"Auto unlock resumed after bot restart.\n"
                            f"Auto unlock is active and waiting for 00:00 China time.\n"
                            f"Time remaining: {time_str_en}"
                        )
                    else:
                        message = (
                            f"Wznowiono auto unlock po restarcie bota.\n"
                            f"Auto unlock działa i czeka na 00:00 czasu chińskiego.\n"
                            f"Pozostały czas: {time_str}"
                        )
                    try:
                        await app.bot.send_message(chat_id=user_id, text=message)
                    except Exception as e:
                        print(f"Failed to send resume message to {user_id}: {e}")
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('setup', setup_start)],
        states={
            SETUP_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_login)],
            SETUP_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_password)],
        },
        fallbacks=[CommandHandler('cancel', setup_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("accesscode", accesscode))
    app.add_handler(conv_handler)

    app.add_handler(CommandHandler("manual_unlock", manual_unlock_command))
    app.add_handler(CommandHandler("auto_unlock_start", auto_unlock_start))
    app.add_handler(CommandHandler("auto_unlock_stop", auto_unlock_stop))

    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("clear_data", clear_data_command))

    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    print("Bot started. Press Ctrl+C to stop.")

    # Wznawiamy auto_unlock po restarcie
    await resume_all_auto_unlocks(app)

    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    import asyncio
    asyncio.get_event_loop().run_until_complete(main())
