"""Mail access through the Gmail API, behind a small interface so another provider can slot in."""

from __future__ import annotations

import base64
import email
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from typing import Protocol

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"]


@dataclass
class InboundMail:
    cursor: int  # when Gmail received it, in epoch ms: increases with each new message
    sender: str
    subject: str
    html: str | None
    text: str | None
    message_id: str | None


class MailClient(Protocol):
    def fetch_since(self, cursor: int, limit: int = 50) -> list[InboundMail]: ...

    def send(self, to: str, subject: str, html: str, text: str) -> None: ...


class MailError(RuntimeError):
    pass


def _decode(value: str | None) -> str:
    return str(make_header(decode_header(value))) if value else ""


def _bodies(message: Message) -> tuple[str | None, str | None]:
    html = text = None
    for part in message.walk() if message.is_multipart() else [message]:
        if part.get_content_maintype() == "multipart" or part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        decoded = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/html" and html is None:
            html = decoded
        elif part.get_content_type() == "text/plain" and text is None:
            text = decoded
    return html, text


class GmailApi:
    """Gmail over its REST API with an OAuth refresh token (minted once by `hunter-gmail-auth`)."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str, http: httpx.Client | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.http = http or httpx.Client(timeout=30)
        self._access_token: str | None = None

    def _token(self) -> str:
        if self._access_token is None:
            r = self.http.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            if r.is_error:
                # invalid_grant means the token was revoked or expired: mint a new one.
                raise MailError(f"Gmail token refresh failed ({r.status_code}): {r.text[:300]}")
            self._access_token = r.json()["access_token"]
        return self._access_token

    def _call(self, method: str, path: str, **kwargs) -> dict:
        r = self.http.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {self._token()}"}, **kwargs)
        if r.is_error:
            raise MailError(f"Gmail API {method} {path} failed ({r.status_code}): {r.text[:300]}")
        return r.json()

    def fetch_since(self, cursor: int, limit: int = 50) -> list[InboundMail]:
        query = "in:inbox -from:me"
        if cursor:
            query += f" after:{cursor // 1000}"  # whole seconds; exact filtering below
        listing = self._call("GET", "/messages", params={"q": query, "maxResults": limit})
        mails = []
        for ref in listing.get("messages", []):
            raw = self._call("GET", f"/messages/{ref['id']}", params={"format": "raw"})
            received = int(raw.get("internalDate", 0))
            if received <= cursor:
                continue
            message = email.message_from_bytes(base64.urlsafe_b64decode(raw["raw"]))
            html, text = _bodies(message)
            mails.append(
                InboundMail(
                    cursor=received,
                    sender=_decode(message.get("From")),
                    subject=_decode(message.get("Subject")),
                    html=html,
                    text=text,
                    message_id=message.get("Message-ID"),
                )
            )
        return sorted(mails, key=lambda m: m.cursor)

    def send(self, to: str, subject: str, html: str, text: str) -> None:
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        self._call("POST", "/messages/send", json={"raw": raw})
