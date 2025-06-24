from playwright.sync_api import sync_playwright
import time
import os

LOGIN_URL = "https://sgp-api.buy.mi.com/bbs/api/global/user/login-in?callbackurl=https%3A%2F%2Fc.mi.com%2Fglobal%2F"
TOKEN_FILE = "token.txt"

def login_and_get_token(email, password, browser_type, token_name):
    with sync_playwright() as p:
        browser = getattr(p, browser_type).launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print(f"\n[{browser_type.upper()}] Otwieranie strony logowania...")
        page.goto(LOGIN_URL)
        page.wait_for_load_state("networkidle")

        print(f"[{browser_type.upper()}] Logowanie...")
        page.fill('input[name="account"]', email)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')

        print(f"[{browser_type.upper()}] Czekam na cookies... (10s)")
        time.sleep(10)

        cookies = context.cookies()
        browser.close()

        for cookie in cookies:
            if cookie['name'] == token_name:
                print(f"[{browser_type.upper()}] ✅ Token '{token_name}' znaleziony.")
                return cookie['value']

        print(f"[{browser_type.upper()}] ❌ Token '{token_name}' NIE znaleziony.")
        return None

def save_tokens_to_file(bbs_token, pop_token):
    lines = [
        bbs_token or "MISSING_TOKEN",
        pop_token or "MISSING_TOKEN",
        bbs_token or "MISSING_TOKEN",
        pop_token or "MISSING_TOKEN"
    ]
    with open(TOKEN_FILE, "w") as f:
        for line in lines:
            f.write(line + "\n")
    print(f"\n✅ Tokeny zapisane do pliku '{TOKEN_FILE}':")
    for i, line in enumerate(lines, 1):
        print(f"  {i}: {line}")

def main():
    email = input("🔐 Login (email/telefon): ").strip()
    password = input("🔐 Hasło: ").strip()

    # Token z Firefoxa
    bbs_token = login_and_get_token(email, password, "firefox", "new_bbs_serviceToken")

    # Token z Chrome (Chromium)
    pop_token = login_and_get_token(email, password, "chromium", "popRunToken")

    # Zapisz do pliku
    save_tokens_to_file(bbs_token, pop_token)

if __name__ == "__main__":
    main()
