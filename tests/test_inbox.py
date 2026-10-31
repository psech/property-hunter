from types import SimpleNamespace

from google.genai import errors

from hunter.cache import JsonCache
from hunter.extract import Extractor, LlmListings
from hunter.llm import Llm
from hunter.mail import InboundMail
from hunter.sources import inbox


def _mail(uid: int, subject: str) -> InboundMail:
    return InboundMail(uid, "Pulse <a@pulse.example>", subject, None, f"{subject} at 3 Oak Rd, Gymea", None)


class FakeMailbox:
    def __init__(self, mails):
        self.mails = mails

    def fetch_since(self, last_uid, limit=50):
        return [m for m in self.mails if m.uid > last_uid]


def fake_llm(answers, fallback_model=None) -> Llm:
    """An Llm whose Gemini client replies from `answers`: an exception to raise, or an address."""
    calls = []

    def generate_content(model, contents, config):
        calls.append(model)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        parsed = LlmListings.model_validate({"listings": [{"address": answer, "suburb": "Gymea"}]})
        return SimpleNamespace(parsed=parsed, text=None)

    llm = Llm(None, "main-model", max_calls=50, fallback_model=fallback_model)
    llm._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    llm.calls_made = calls
    return llm


def overloaded() -> errors.APIError:
    return errors.APIError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})


def test_failure_keeps_mail_read_so_far_and_retries_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr("hunter.llm.time.sleep", lambda s: None)
    llm = fake_llm(["3 Oak Rd"] + [overloaded()] * 5)
    mailbox = FakeMailbox([_mail(4, "Off-market"), _mail(9, "Coming soon"), _mail(12, "Just listed")])

    listings, last_uid, error = inbox.collect(mailbox, Extractor(llm, JsonCache("x", tmp_path)), 0)
    assert [listing.address for listing in listings] == ["3 Oak Rd"]
    assert last_uid == 4  # mail 9 failed, so 9 and 12 are read next run
    assert "503" in error


def test_overloaded_model_switches_to_fallback_for_the_rest_of_the_run(tmp_path):
    llm = fake_llm([overloaded(), "3 Oak Rd", "5 Elm St"], fallback_model="lite-model")
    extractor = Extractor(llm, JsonCache("x", tmp_path))

    mailbox = FakeMailbox([_mail(1, "One"), _mail(2, "Two")])
    listings, last_uid, error = inbox.collect(mailbox, extractor, 0)
    assert [listing.address for listing in listings] == ["3 Oak Rd", "5 Elm St"]
    assert (last_uid, error) == (2, None)
    assert llm.calls_made == ["main-model", "lite-model", "lite-model"]
