"""One-off: mint a Gmail refresh token for the alerts account. Run on your own machine.

    uv run hunter-gmail-auth --client-id ... --client-secret ...

It opens Google's consent page in your browser, catches the redirect on localhost, and prints
the refresh token to store as the GMAIL_REFRESH_TOKEN secret. Sign in as the alerts account.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import secrets
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from hunter.mail import SCOPES, TOKEN_URL

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--client-id", required=True)
    p.add_argument("--client-secret", required=True)
    args = p.parse_args()

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            if "code" not in params and "error" not in params:
                self.send_response(404)
                self.end_headers()
                return
            result.update(params)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Done. You can close this tab and return to the terminal.")

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urlencode(
        {
            "client_id": args.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # always return a refresh token
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    print(f"Opening the consent page. If no browser opens, visit:\n{url}\n")
    webbrowser.open(url)
    server.timeout = 5
    deadline = time.monotonic() + 300
    while not result and time.monotonic() < deadline:  # ignore stray requests such as /favicon.ico
        server.handle_request()
    server.server_close()

    if result.get("state") != state or "code" not in result:
        raise SystemExit(f"Authorisation failed: {result.get('error', 'no response within 5 minutes')}")
    r = httpx.post(
        TOKEN_URL,
        data={
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "code": result["code"],
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    if r.is_error:
        raise SystemExit(f"Token exchange failed ({r.status_code}): {r.text}")
    token = r.json().get("refresh_token")
    if not token:
        raise SystemExit("Google returned no refresh token; revoke the app's access and run this again.")
    print("Store this as the GMAIL_REFRESH_TOKEN secret (and in .env for local runs):\n")
    print(token)


if __name__ == "__main__":
    main()
