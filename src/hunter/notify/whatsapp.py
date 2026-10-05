"""WhatsApp ping through CallMeBot (free, text only, about 25 messages per 4 hours)."""

from __future__ import annotations

import httpx


def send_whatsapp(phone: str, apikey: str, text: str) -> None:
    response = httpx.get(
        "https://api.callmebot.com/whatsapp.php",
        params={"phone": phone, "text": text, "apikey": apikey},
        timeout=30,
    )
    response.raise_for_status()
    if "error" in response.text.lower()[:200]:
        raise RuntimeError(f"CallMeBot rejected the message: {response.text[:200]}")
