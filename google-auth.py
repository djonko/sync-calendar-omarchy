#!/usr/bin/env python3
"""
Google Calendar OAuth2 Authorization Helper for Omarchy Calendar Plugin.
Acquires and stores a refresh token for accessing private/shared Google Calendars via the API.
"""

import os
import sys
import json
import time
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

auth_code = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)

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
                <p>You can close this tab and return to the terminal.</p>
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
        return json.loads(resp.read().decode("utf-8"))


def main():
    os.makedirs(STATE_DIR, exist_ok=True)

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    existing_auth = {}
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as f:
                existing_auth = json.load(f)
                client_id = client_id or existing_auth.get("client_id", "")
                client_secret = client_secret or existing_auth.get("client_secret", "")
        except Exception:
            pass

    if len(sys.argv) >= 3:
        client_id = sys.argv[1].strip()
        client_secret = sys.argv[2].strip()

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

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        })
    )

    print("\nStarting local authentication server on port", PORT, "...")
    server = HTTPServer(("127.0.0.1", PORT), OAuthCallbackHandler)
    server.timeout = 120

    print("Opening browser for authorization...")
    print("If it does not open automatically, visit:")
    print(auth_url)
    print()
    webbrowser.open(auth_url)

    print("Waiting for authorization in browser (timeout: 2 minutes)...")
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

        with open(AUTH_FILE, "w", encoding="utf-8") as f:
            json.dump(auth_data, f, indent=2)

        print("\n" + "=" * 60)
        print("SUCCESS! Google OAuth credentials saved to:")
        print(f"  {AUTH_FILE}")
        print("=" * 60)

    except Exception as e:
        print("Failed to exchange tokens:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
