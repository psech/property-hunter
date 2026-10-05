"""Mail access behind a small interface, so a Gmail API client can replace IMAP/SMTP if ever needed."""

from __future__ import annotations

import email
import imaplib
import smtplib
from dataclasses import dataclass
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from typing import Protocol


@dataclass
class InboundMail:
    uid: int
    sender: str
    subject: str
    html: str | None
    text: str | None
    message_id: str | None


class MailClient(Protocol):
    def fetch_since(self, last_uid: int, limit: int = 50) -> list[InboundMail]: ...

    def send(self, to: str, subject: str, html: str, text: str) -> None: ...


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


class GmailImapSmtp:
    """Gmail over IMAP/SMTP with an app password (requires 2-Step Verification on the account)."""

    def __init__(self, address: str, app_password: str):
        self.address = address
        self.password = app_password

    def fetch_since(self, last_uid: int, limit: int = 50) -> list[InboundMail]:
        with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
            imap.login(self.address, self.password)
            imap.select("INBOX", readonly=True)
            status, data = imap.uid("search", None, f"UID {last_uid + 1}:*")
            if status != "OK":
                return []
            # 'UID n:*' always matches the newest message, even when n is past it.
            uids = [int(u) for u in data[0].split() if int(u) > last_uid][:limit]
            mails = []
            for uid in uids:
                status, parts = imap.uid("fetch", str(uid), "(RFC822)")
                if status != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                message = email.message_from_bytes(parts[0][1])
                html, text = _bodies(message)
                mails.append(
                    InboundMail(
                        uid=uid,
                        sender=_decode(message.get("From")),
                        subject=_decode(message.get("Subject")),
                        html=html,
                        text=text,
                        message_id=message.get("Message-ID"),
                    )
                )
            return mails

    def send(self, to: str, subject: str, html: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = f"Property Hunter <{self.address}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(self.address, self.password)
            smtp.send_message(message)
