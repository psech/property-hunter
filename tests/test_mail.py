import email
from email.message import EmailMessage

from hunter import mail
from hunter.mail import GmailImapSmtp


def _message(subject: str, html: str) -> bytes:
    message = EmailMessage()
    message["From"] = "Pulse Property <alerts@pulse.example>"
    message["Subject"] = subject
    message.set_content("plain version")
    message.add_alternative(html, subtype="html")
    return message.as_bytes()


class FakeImap:
    def __init__(self, messages: dict[int, bytes]):
        self.messages = messages
        self.login_args = None
        self.readonly = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.login_args = (user, password)

    def select(self, mailbox, readonly=False):
        self.readonly = readonly
        return "OK", [str(len(self.messages)).encode()]

    def uid(self, command, *args):
        if command == "search":
            start = int(args[1].split()[1].split(":")[0])
            # Like Gmail, 'n:*' still matches the newest message when n is past it.
            found = [u for u in self.messages if u >= start] or [max(self.messages)]
            return "OK", [" ".join(map(str, found)).encode()]
        return "OK", [(b"header", self.messages[int(args[0])])]


class FakeSmtp:
    sent: list = []

    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, message):
        FakeSmtp.sent.append((self.login_args, message))


def test_fetch_since_returns_only_newer_mail_read_only(monkeypatch):
    imap = FakeImap({5: _message("Old", "<p>old</p>"), 7: _message("Off-market", "<p>3 Oak Rd</p>")})
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: imap)

    mails = GmailImapSmtp("me@gmail.com", "abcd efgh ijkl mnop").fetch_since(last_uid=5)
    assert [(m.uid, m.subject) for m in mails] == [(7, "Off-market")]
    assert "3 Oak Rd" in mails[0].html and mails[0].sender == "Pulse Property <alerts@pulse.example>"
    assert imap.login_args == ("me@gmail.com", "abcdefghijklmnop")  # spaces from Google's display dropped
    assert imap.readonly  # never marks mail as read


def test_fetch_since_with_nothing_new(monkeypatch):
    monkeypatch.setattr(mail.imaplib, "IMAP4_SSL", lambda host: FakeImap({7: _message("Seen", "<p>x</p>")}))
    assert GmailImapSmtp("me@gmail.com", "pw").fetch_since(last_uid=7) == []


def test_send_builds_multipart_message(monkeypatch):
    FakeSmtp.sent = []
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSmtp)
    GmailImapSmtp("me@gmail.com", "pw").send("you@example.com", "Digest", "<b>hi</b>", "hi")
    (login, message), = FakeSmtp.sent
    assert login == ("me@gmail.com", "pw")
    parsed = email.message_from_bytes(message.as_bytes())
    assert parsed["To"] == "you@example.com" and parsed["Subject"] == "Digest" and parsed.is_multipart()
