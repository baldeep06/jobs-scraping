import smtplib
from collections.abc import Mapping
from email.message import EmailMessage

import httpx

DEFAULT_FROM = "Intern Radar <onboarding@resend.dev>"


class SendError(Exception):
    """Raised with a message that is safe to print in a public log."""


def _require(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise SendError(f"{name} is not set")
    return value


def send_email(
    subject: str,
    html: str,
    text: str,
    env: Mapping[str, str],
    client: httpx.Client | None = None,
) -> None:
    to = _require(env, "DIGEST_TO")
    sender = env.get("DIGEST_FROM") or DEFAULT_FROM
    if env.get("DIGEST_TRANSPORT") == "smtp":
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, sender, to
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP_SSL(_require(env, "SMTP_HOST"), 465) as smtp:
                smtp.login(_require(env, "SMTP_USER"), _require(env, "SMTP_PASSWORD"))
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            raise SendError(f"SMTP send failed ({type(e).__name__})") from None
        return
    key = _require(env, "RESEND_API_KEY")
    http = client or httpx.Client(timeout=20)
    try:
        resp = http.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json={"from": sender, "to": [to], "subject": subject, "html": html, "text": text},
        )
    except httpx.HTTPError as e:
        raise SendError(f"Resend request failed ({type(e).__name__})") from None
    if resp.status_code >= 400:
        raise SendError(f"Resend rejected the email (HTTP {resp.status_code})")
