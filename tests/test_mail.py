import base64
import email
import json
from email.message import EmailMessage

import httpx

from hunter.mail import GmailApi


def _raw(subject: str, html: str) -> str:
    message = EmailMessage()
    message["From"] = "Pulse Property <alerts@pulse.example>"
    message["Subject"] = subject
    message.set_content("plain version")
    message.add_alternative(html, subtype="html")
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def make_client(handler) -> GmailApi:
    return GmailApi("id", "secret", "refresh", http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_fetch_since_refreshes_token_and_filters_by_cursor():
    seen = []
    messages = {
        "old": {"internalDate": "1000", "raw": _raw("Old", "<p>old</p>")},
        "b": {"internalDate": "3000", "raw": _raw("Second", "<p>Off-market: 3 Oak Rd</p>")},
        "a": {"internalDate": "2000", "raw": _raw("First", "<p>Coming soon</p>")},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            assert b"grant_type=refresh_token" in request.content
            return httpx.Response(200, json={"access_token": "tok"})
        assert request.headers["Authorization"] == "Bearer tok"
        if request.url.path.endswith("/messages"):
            assert "after:1" in request.url.params["q"]
            return httpx.Response(200, json={"messages": [{"id": i} for i in ("b", "a", "old")]})
        return httpx.Response(200, json=messages[request.url.path.rsplit("/", 1)[1]])

    mails = make_client(handler).fetch_since(cursor=1000)
    assert [m.subject for m in mails] == ["First", "Second"]  # oldest first, cursor excluded
    assert mails[1].cursor == 3000 and "3 Oak Rd" in mails[1].html
    assert mails[0].sender == "Pulse Property <alerts@pulse.example>"
    assert sum(1 for r in seen if r.url.host == "oauth2.googleapis.com") == 1  # token reused


def test_send_posts_raw_message():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok"})
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "x"})

    make_client(handler).send("me@example.com", "Digest", "<b>hi</b>", "hi")
    message = email.message_from_bytes(base64.urlsafe_b64decode(sent["raw"]))
    assert message["To"] == "me@example.com" and message["Subject"] == "Digest"
    assert message.is_multipart()


def test_revoked_token_raises_clear_error():
    import pytest

    from hunter.mail import MailError

    client = make_client(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(MailError, match="token refresh failed"):
        client.fetch_since(0)
