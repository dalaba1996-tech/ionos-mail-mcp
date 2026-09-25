import os
import imaplib
import email
from email.header import decode_header
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "IONOS Mail",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "ionos-mail-mcp-1.onrender.com",
            "ionos-mail-mcp-1.onrender.com:*",
        ],
        allowed_origins=[
            "https://ionos-mail-mcp-1.onrender.com",
        ],
    ),
)

IMAP_HOST = os.environ.get("IMAP_HOST", "imap.ionos.fr")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")


def connect_imap():
    if not EMAIL_USER or not EMAIL_PASSWORD:
        raise RuntimeError("Identifiants IONOS non configurés.")

    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    mail.login(EMAIL_USER, EMAIL_PASSWORD)
    return mail


def decode_text(value):
    if not value:
        return ""

    parts = decode_header(value)
    result = ""

    for text, charset in parts:
        if isinstance(text, bytes):
            result += text.decode(charset or "utf-8", errors="replace")
        else:
            result += text

    return result


@mcp.tool()
def recent_emails(limit: int = 10) -> str:
    """Retourne les derniers emails reçus dans la boîte IONOS."""

    limit = max(1, min(limit, 50))

    mail = connect_imap()

    try:
        mail.select("INBOX", readonly=True)
        status, data = mail.search(None, "ALL")

        if status != "OK":
            return "Impossible de rechercher les emails."

        ids = data[0].split()[-limit:]
        results = []

        for message_id in reversed(ids):
            status, msg_data = mail.fetch(
                message_id,
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
            )

            if status != "OK":
                continue

            raw = next(
                (
                    item[1]
                    for item in msg_data
                    if isinstance(item, tuple)
                ),
                None,
            )

            if not raw:
                continue

            msg = email.message_from_bytes(raw)

            results.append(
                f"De: {decode_text(msg.get('From'))}\n"
                f"Objet: {decode_text(msg.get('Subject'))}\n"
                f"Date: {msg.get('Date', '')}"
            )

        return "\n\n---\n\n".join(results) or "Aucun email trouvé."

    finally:
        try:
            mail.logout()
        except Exception:
            pass


@mcp.tool()
def search_emails(query: str, limit: int = 10) -> str:
    """Recherche des emails contenant un texte dans l'objet."""

    limit = max(1, min(limit, 50))
    mail = connect_imap()

    try:
        mail.select("INBOX", readonly=True)

        safe_query = query.replace('"', "")
        status, data = mail.search(
            None,
            "SUBJECT",
            f'"{safe_query}"'
        )

        if status != "OK":
            return "Recherche impossible."

        ids = data[0].split()[-limit:]
        results = []

        for message_id in reversed(ids):
            status, msg_data = mail.fetch(
                message_id,
                "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])"
            )

            if status != "OK":
                continue

            raw = next(
                (
                    item[1]
                    for item in msg_data
                    if isinstance(item, tuple)
                ),
                None,
            )

            if not raw:
                continue

            msg = email.message_from_bytes(raw)

            results.append(
                f"De: {decode_text(msg.get('From'))}\n"
                f"Objet: {decode_text(msg.get('Subject'))}\n"
                f"Date: {msg.get('Date', '')}"
            )

        return "\n\n---\n\n".join(results) or "Aucun email trouvé."

    finally:
        try:
            mail.logout()
        except Exception:
            pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port

    mcp.run(transport="streamable-http")
