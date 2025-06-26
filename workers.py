import os
import time
import json
import asyncio
import random
import hashlib
import urllib3
from datetime import datetime, timedelta
import pytz

from icmplib import ping
from playwright.sync_api import sync_playwright

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

RUNNING_AUTO_UNLOCKS = {}  # user_id -> asyncio.Task

MI_SERVERS = ['161.117.96.161', '20.157.18.26']
MI_SERVER_DOMAIN = 'sgp-api.buy.mi.com'


def generate_device_id():
    random_data = f"{random.random()}-{time.time()}"
    device_id = hashlib.sha1(random_data.encode('utf-8')).hexdigest().upper()
    return device_id


def save_tokens(user_id: int, tokens: dict):
    user_dir = os.path.join(DATA_DIR, str(user_id))
    if not os.path.exists(user_dir):
        print(f"[Error] User directory {user_dir} does not exist.")
        return False
    token_file = os.path.join(user_dir, "token")
    with open(token_file, "w", encoding="utf-8") as f:
        f.write(tokens.get("new_bbs_serviceToken", "MISSING_TOKEN") + "\n")
        f.write(tokens.get("popRunToken", "MISSING_TOKEN") + "\n")
    print(f"[Info] Tokens saved for user {user_id} to {token_file}")
    return True


async def get_tokens_playwright(user_id: int, email: str, password: str):
    LOGIN_URL = "https://sgp-api.buy.mi.com/bbs/api/global/user/login-in?callbackurl=https%3A%2F%2Fc.mi.com%2Fglobal%2F"
    loop = asyncio.get_event_loop()

    def run_sync():
        with sync_playwright() as p:
            # Firefox - new_bbs_serviceToken
            browser_firefox = p.firefox.launch(headless=True)
            context_firefox = browser_firefox.new_context()
            page_firefox = context_firefox.new_page()
            page_firefox.goto(LOGIN_URL)
            page_firefox.wait_for_load_state("networkidle")
            page_firefox.fill('input[name="account"]', email)
            page_firefox.fill('input[name="password"]', password)
            page_firefox.click('button[type="submit"]')
            time.sleep(10)  # wait for token cookies
            cookies_firefox = context_firefox.cookies()
            browser_firefox.close()

            bbs_token = None
            for c in cookies_firefox:
                if c.get("name") == "new_bbs_serviceToken":
                    bbs_token = c.get("value")
                    break

            # Chromium - popRunToken
            browser_chromium = p.chromium.launch(headless=True)
            context_chromium = browser_chromium.new_context()
            page_chromium = context_chromium.new_page()
            page_chromium.goto(LOGIN_URL)
            page_chromium.wait_for_load_state("networkidle")
            page_chromium.fill('input[name="account"]', email)
            page_chromium.fill('input[name="password"]', password)
            page_chromium.click('button[type="submit"]')
            time.sleep(10)  # wait for token cookies
            cookies_chromium = context_chromium.cookies()
            browser_chromium.close()

            pop_token = None
            for c in cookies_chromium:
                if c.get("name") == "popRunToken":
                    pop_token = c.get("value")
                    break

            return {
                "new_bbs_serviceToken": bbs_token or "MISSING",
                "popRunToken": pop_token or "MISSING"
            }

    tokens = await loop.run_in_executor(None, run_sync)

    saved = save_tokens(user_id, tokens)
    if not saved:
        return None
    return tokens


# ---- Dodajemy funkcję testową do zwracania tokenów ----
async def test_tokens(user_id: int, user_data: dict):
    tokens = await get_tokens_playwright(user_id, user_data.get("email"), user_data.get("password"))
    return tokens


class HTTP11Session:
    def __init__(self):
        self.http = urllib3.PoolManager(
            maxsize=10,
            retries=True,
            timeout=urllib3.Timeout(connect=2.0, read=15.0),
            headers={}
        )

    def make_request(self, method, url, headers=None, body=None):
        try:
            request_headers = {}
            if headers:
                request_headers.update(headers)
            request_headers['Content-Type'] = 'application/json; charset=utf-8'

            if method == 'POST':
                if body is None:
                    body = '{"is_retry":true}'.encode('utf-8')
                request_headers['Content-Length'] = str(len(body))
                request_headers['Accept-Encoding'] = 'gzip, deflate, br'
                request_headers['User-Agent'] = 'okhttp/4.12.0'
                request_headers['Connection'] = 'keep-alive'

            response = self.http.request(
                method,
                url,
                headers=request_headers,
                body=body,
                preload_content=False
            )
            return response
        except Exception as e:
            print(f"[ERROR] HTTP request failed: {e}")
            return None


async def send_unlock_request(tokens: dict, device_id: str, send_status_func):
    session = HTTP11Session()

    # Ping servers to pick best
    best_server = None
    best_ping = None
    for srv in MI_SERVERS:
        try:
            res = ping(srv, count=1, timeout=2)
            if res.is_alive:
                if best_ping is None or res.avg_rtt < best_ping:
                    best_ping = res.avg_rtt
                    best_server = srv
        except Exception:
            continue

    if best_server is None:
        await send_status_func("Failed to ping Xiaomi servers, using default server.")
        best_server = MI_SERVERS[0]

    await send_status_func(f"Using Xiaomi server: {best_server} (avg ping: {best_ping} ms)")

    url = f"https://{MI_SERVER_DOMAIN}/bbs/api/global/apply/bl-auth"
    headers = {
        "Cookie": f"new_bbs_serviceToken={tokens['new_bbs_serviceToken']};versionCode=500411;versionName=5.4.11;deviceId={device_id};"
    }

    response = session.make_request("POST", url, headers=headers)
    if response is None:
        await send_status_func("[ERROR] Failed to send unlock request.")
        return False

    try:
        response_data = json.loads(response.data.decode('utf-8'))
        code = response_data.get("code")
        data = response_data.get("data", {})

        if code == 0:
            apply_result = data.get("apply_result")
            if apply_result == 1:
                await send_status_func("[OK] Unlock request accepted. Check your account status later.")
            elif apply_result == 3:
                await send_status_func("[INFO] Attempt limit reached. Try again later.")
            elif apply_result == 4:
                await send_status_func("[INFO] Account temporarily blocked. Try later.")
            else:
                await send_status_func(f"[INFO] Unknown apply_result: {apply_result}")
            return True
        else:
            await send_status_func(f"[ERROR] Unexpected response code: {code}\nFull response: {response_data}")
            return False
    except Exception as e:
        await send_status_func(f"[ERROR] Failed to parse response JSON: {e}")
        return False


async def manual_unlock(user_id: int, user_data: dict, bot):
    async def send_status(msg: str):
        try:
            await bot.send_message(chat_id=user_id, text=msg)
        except Exception as e:
            print(f"Error sending status to {user_id}: {e}")

    email = user_data.get("email")
    password = user_data.get("password")
    if not email or not password:
        await send_status("Email or password missing. Please setup your credentials first.")
        return None

    await send_status("Starting manual unlock: fetching fresh tokens...")
    tokens = await get_tokens_playwright(user_id, email, password)
    if not tokens:
        await send_status("Failed to fetch tokens. Cannot proceed with unlock.")
        return None

    await send_status("Tokens fetched successfully. Attempting unlock...")

    device_id = generate_device_id()
    await send_unlock_request(tokens, device_id, send_status)

    await send_status("Manual unlock process finished.")
    return tokens


def save_status(user_id: int, status: str):
    user_dir = os.path.join(DATA_DIR, str(user_id))
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    status_file = os.path.join(user_dir, "status")
    with open(status_file, "w", encoding="utf-8") as f:
        f.write(status)


def load_status(user_id: int):
    status_file = os.path.join(DATA_DIR, str(user_id), "status")
    if not os.path.exists(status_file):
        return None
    with open(status_file, "r", encoding="utf-8") as f:
        return f.read().strip()


async def auto_unlock(user_id: int, user_data: dict, bot):
    async def send_status(msg: str):
        try:
            await bot.send_message(chat_id=user_id, text=msg)
        except Exception as e:
            print(f"Error sending status to {user_id}: {e}")

    email = user_data.get("email")
    password = user_data.get("password")
    if not email or not password:
        await send_status("Email or password missing. Cannot run auto unlock.")
        return

    # Zapisywanie statusu 'autounlock' podczas startu
    save_status(user_id, "autounlock")

    tz_china = pytz.timezone('Asia/Shanghai')
    now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)

    # Obliczamy kolejną północ (00:00 następnego dnia, jeśli już po północy)
    now_china = now_utc.astimezone(tz_china)
    midnight_china = now_china.replace(hour=0, minute=0, second=0, microsecond=0)
    if now_china >= midnight_china:
        midnight_china += timedelta(days=1)

    while True:
        # Liczymy czas do pobrania tokenów (5 minut przed północą)
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_china = now_utc.astimezone(tz_china)
        seconds_until_midnight = (midnight_china - now_china).total_seconds()
        seconds_until_token_fetch = seconds_until_midnight - 5 * 60

        if seconds_until_token_fetch > 0:
            # Nie wyświetlamy wiadomości o czekaniu, tylko śpimy
            await asyncio.sleep(seconds_until_token_fetch)

        # Pobieramy tokeny 5 minut przed północą
        await send_status("Fetching fresh tokens for auto unlock...")
        tokens = await get_tokens_playwright(user_id, email, password)
        if not tokens:
            await send_status("Failed to fetch tokens, retrying in 30 seconds...")
            await asyncio.sleep(30)
            continue
        else:
            await send_status("Tokens fetched successfully. Will attempt unlock in 5 minutes.")

        # Ping serwera Xiaomi (1 minuta przed odblokowaniem)
        best_server = None
        best_ping = None
        for srv in MI_SERVERS:
            try:
                res = ping(srv, count=3, timeout=2)
                if res.is_alive:
                    avg_ping = res.avg_rtt
                    if best_ping is None or avg_ping < best_ping:
                        best_ping = avg_ping
                        best_server = srv
            except Exception:
                continue

        if best_server is None:
            await send_status("Failed to ping Xiaomi servers. Using default server time offset 0.")
            best_ping = 0

        offset_seconds = (best_ping / 2) / 1000 if best_ping else 0
        await send_status(f"Best Xiaomi server: {best_server} with avg ping {best_ping} ms.")
        await send_status(f"Offsetting unlock time by {offset_seconds:.3f} seconds for ping compensation.")

        # Obliczamy dokładny czas do 00:00 + offset
        now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
        now_china = now_utc.astimezone(tz_china)
        target_time = midnight_china + timedelta(seconds=offset_seconds)
        time_until_target = (target_time - now_china).total_seconds()

        if time_until_target > 0:
            await send_status(f"Waiting {time_until_target:.2f} seconds until exact unlock time (00:00)...")
            await asyncio.sleep(time_until_target)
        else:
            await send_status("Unlock time passed, sending immediately.")

        device_id = generate_device_id()
        await send_unlock_request(tokens, device_id, send_status)

        # Ustawiamy midnight na kolejny dzień
        midnight_china += timedelta(days=1)

        await send_status("Auto unlock cycle finished. Waiting for next day...")


async def start_auto_unlock_for_user(user_id: int, user_data: dict, bot):
    if user_id in RUNNING_AUTO_UNLOCKS:
        return "Auto unlock already running"

    task = asyncio.create_task(auto_unlock(user_id, user_data, bot))
    RUNNING_AUTO_UNLOCKS[user_id] = task

    def done_callback(t):
        RUNNING_AUTO_UNLOCKS.pop(user_id, None)
        save_status(user_id, "stopped")  # status po zatrzymaniu

    task.add_done_callback(done_callback)
    return "Auto unlock started"


def is_auto_unlock_running(user_id: int):
    return user_id in RUNNING_AUTO_UNLOCKS


def stop_auto_unlock(user_id: int):
    task = RUNNING_AUTO_UNLOCKS.pop(user_id, None)
    if task:
        task.cancel()
        save_status(user_id, "stopped")
