#!/usr/bin/env python3
"""
Google Calendar OAuth2 Authorization Helper for Omarchy Calendar Plugin.
Acquires and stores a refresh token for accessing private/shared Google Calendars via the API.
"""

import os
import sys
import json
import time
import secrets
import webbrowser
import urllib.request
import urllib.parse
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

STATE_DIR = os.path.expanduser("~/.local/state/omarchy")
AUTH_FILE = os.path.join(STATE_DIR, "google-auth.json")
PORT = 8088
REDIRECT_URI = f"http://127.0.0.1:{PORT}"
SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

MAX_API_BYTES = 5 * 1024 * 1024     # 5 MB limit for API JSON responses
MAX_CONFIG_BYTES = 1 * 1024 * 1024  # 1 MB limit for config/auth files

auth_code = None
expected_state = None


def safe_read_bytes(stream, max_bytes=MAX_API_BYTES):
    """
    Reads binary content from stream up to max_bytes + 1.
    Raises ValueError if content exceeds max_bytes to prevent unbounded memory consumption.
    """
    chunks = []
    total = 0
    chunk_size = 64 * 1024
    while total <= max_bytes:
        chunk = stream.read(min(chunk_size, max_bytes - total + 1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"Content size exceeded safety limit of {max_bytes} bytes")
    return b"".join(chunks)


def safe_read_text(stream, max_bytes=MAX_CONFIG_BYTES):
    """
    Reads text content from stream up to max_bytes + 1 chars.
    Raises ValueError if content exceeds max_bytes to prevent unbounded memory consumption.
    """
    chunks = []
    total = 0
    chunk_size = 64 * 1024
    while total <= max_bytes:
        chunk = stream.read(min(chunk_size, max_bytes - total + 1))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"Content size exceeded safety limit of {max_bytes} characters")
    return "".join(chunks)


def safe_load_json(file_path, max_bytes=MAX_CONFIG_BYTES):
    """
    Safely reads and parses JSON from a file ensuring size is strictly bounded.
    """
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        text = safe_read_text(f, max_bytes=max_bytes)
        return json.loads(text)


def write_secure_json(path, data, mode=0o600):
    """Write sensitive JSON data atomically with owner-only permissions (0600)."""
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, mode=0o700, exist_ok=True)
    tmp_path = path + f".tmp.{os.getpid()}"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code, expected_state
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

        received_state = params.get("state", [""])[0]
        if not expected_state or not received_state or not secrets.compare_digest(received_state, expected_state):
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <html>
            <head><title>Authentication Failed</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px; background: #181825; color: #cdd6f4;">
                <h1 style="color: #f38ba8;">Authentication Failed</h1>
                <p>Invalid or missing OAuth state parameter (CSRF validation failed).</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
            return

        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <html>
            <head><title>Omarchy Calendar Auth</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px; background: #181825; color: #cdd6f4;">
                <h1 style="color: #a6e3a1;">&#10004; Authentication Successful!</h1>
                <p>You have successfully authenticated your Google account with Omarchy.</p>
                <p>You can close this tab and return to the desktop.</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            error = params.get("error", ["Unknown error"])[0]
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = f"""
            <html>
            <body style="font-family: sans-serif; text-align: center; padding: 50px; background: #181825; color: #cdd6f4;">
                <h1 style="color: #f38ba8;">Authentication Failed</h1>
                <p>Error: {error}</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        # Silence standard HTTP request logging
        pass


def exchange_code_for_tokens(client_id, client_secret, code):
    url = "https://oauth2.googleapis.com/token"
    payload = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = safe_read_bytes(resp, max_bytes=MAX_API_BYTES)
        return json.loads(raw.decode("utf-8"))


def main():
    global expected_state
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    existing_auth = safe_load_json(AUTH_FILE, max_bytes=MAX_CONFIG_BYTES) or {}
    client_id = client_id or existing_auth.get("client_id", "")
    client_secret = client_secret or existing_auth.get("client_secret", "")

    if len(sys.argv) >= 3:
        client_id = sys.argv[1].strip()
        client_secret = sys.argv[2].strip()

    if not client_id or not client_secret:
        downloads_dir = os.path.expanduser("~/Downloads")
        if os.path.exists(downloads_dir):
            for fname in os.listdir(downloads_dir):
                if fname.startswith("client_secret_") and fname.endswith(".json"):
                    try:
                        secret_data = safe_load_json(os.path.join(downloads_dir, fname), max_bytes=MAX_CONFIG_BYTES)
                        if secret_data:
                            inst = secret_data.get("installed") or secret_data.get("web", {})
                            if inst.get("client_id") and inst.get("client_secret"):
                                client_id = inst["client_id"]
                                client_secret = inst["client_secret"]
                                print(f"Found and loaded Google OAuth credentials from: ~/Downloads/{fname}")
                                break
                    except Exception:
                        pass

    if not client_id or not client_secret:
        print("=" * 60)
        print("  Omarchy Calendar - Google OAuth2 Setup")
        print("=" * 60)
        print("To connect calendars that require your Google login:")
        print("1. Go to Google Cloud Console: https://console.cloud.google.com/")
        print("2. Enable the 'Google Calendar API'")
        print("3. Under Credentials -> Create Credentials -> 'OAuth client ID'")
        print("   Application type: 'Desktop App'")
        print("=" * 60)
        client_id = input("Enter your Google OAuth Client ID: ").strip()
        client_secret = input("Enter your Google OAuth Client Secret: ").strip()

    if not client_id or not client_secret:
        print("Error: Client ID and Client Secret are required.")
        sys.exit(1)

    expected_state = secrets.token_urlsafe(32)

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": expected_state,
        })
    )

    print("\nStarting local authentication server on 127.0.0.1:", PORT, "...")
    server = HTTPServer(("127.0.0.1", PORT), OAuthCallbackHandler)
    server.timeout = 600

    print("Opening browser for authorization...")
    print("If it does not open automatically, visit:")
    print(auth_url)
    print()
    webbrowser.open(auth_url)

    print("Waiting for authorization in browser (timeout: 10 minutes)...")
    while not auth_code:
        server.handle_request()

    if not auth_code:
        print("Authentication timed out or failed.")
        sys.exit(1)

    print("Authorization code received! Exchanging for tokens...")
    try:
        tokens = exchange_code_for_tokens(client_id, client_secret, auth_code)
        refresh_token = tokens.get("refresh_token") or existing_auth.get("refresh_token")

        if not refresh_token:
            print("Error: No refresh token returned. Try removing app access from Google Account and authenticating again.")
            sys.exit(1)

        auth_data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "access_token": tokens.get("access_token"),
            "expires_at": int(time.time()) + tokens.get("expires_in", 3600),
            "updated_at": int(time.time()),
        }

        write_secure_json(AUTH_FILE, auth_data, mode=0o600)

        print("\n" + "=" * 60)
        print("SUCCESS! Google OAuth credentials saved to:")
        print(f"  {AUTH_FILE}")
        print("=" * 60)

    except Exception as e:
        print("Failed to exchange tokens:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
