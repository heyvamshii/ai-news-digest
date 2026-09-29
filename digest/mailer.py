"""Send the newsletter through SendGrid's Web API (v3 /mail/send).

Uses plain `requests`, so switching to another email provider later means
changing only this file.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

import requests

from config import REQUEST_TIMEOUT

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ANY_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*")
_HINTS = {
    401: "the SendGrid API key is wrong or was deleted",
    403: "the key lacks 'Mail Send' permission, or EMAIL_FROM is not a verified sender in SendGrid",
    413: "the email is too large",
    429: "SendGrid's sending limit was reached (free trial limit?)",
}


class EmailError(Exception):
    """Raised when the newsletter could not be sent."""


@dataclass(frozen=True)
class EmailSettings:
    api_key: str
    sender: str
    sender_name: str
    recipients: tuple[str, ...]
    url: str


def check_settings(settings: EmailSettings) -> None:
    """Fail early with a message that says exactly what is missing."""
    missing = [name for name, value in (("SENDGRID_API_KEY", settings.api_key), ("EMAIL_FROM", settings.sender),
                                        ("EMAIL_TO", settings.recipients)) if not value]
    if missing:
        raise EmailError(f"{', '.join(missing)} not set. Add them to .env (or to GitHub secrets).")
    bad = [a for a in (settings.sender, *settings.recipients) if not _EMAIL.match(a)]
    if bad:
        raise EmailError(f"Not a valid email address: {mask(bad)}")


def build_payload(settings: EmailSettings, subject: str, html: str, text: str) -> dict:
    """One 'personalization' per recipient, so nobody sees the other addresses."""
    return {
        "personalizations": [{"to": [{"email": address}]} for address in settings.recipients],
        "from": {"email": settings.sender, "name": settings.sender_name},
        "subject": subject,
        "content": [{"type": "text/plain", "value": text}, {"type": "text/html", "value": html}],
        "tracking_settings": {"click_tracking": {"enable": False}},   # keep the real article links
    }


def _explain(response: requests.Response) -> str:
    try:
        details = "; ".join(e.get("message", "") for e in response.json().get("errors", []))
    except ValueError:
        details = ""
    hint = _HINTS.get(response.status_code, "unexpected reply from SendGrid")
    details = redact(details)            # SendGrid may echo addresses back; logs can be public
    return f"HTTP {response.status_code}: {hint}" + (f" ({details})" if details else "")


def send(settings: EmailSettings, subject: str, html: str, text: str,
         post=requests.post) -> None:
    check_settings(settings)
    try:
        response = post(
            settings.url,
            json=build_payload(settings, subject, html, text),
            headers={"Authorization": f"Bearer {settings.api_key}"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise EmailError(f"Could not reach SendGrid: {exc.__class__.__name__}") from exc
    if response.status_code != 202:          # SendGrid answers 202 Accepted on success
        raise EmailError(_explain(response))


def _mask_one(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:2]}***@{domain}" if domain else f"{address[:2]}***"


def mask(addresses: Sequence[str]) -> str:
    """'jane.doe@gmail.com' -> 'ja***@gmail.com' so logs don't expose full addresses."""
    return ", ".join(_mask_one(a) for a in addresses)


def redact(text: str) -> str:
    """Mask every email address that appears inside free text."""
    return _ANY_EMAIL.sub(lambda m: _mask_one(m.group(0)), text)
