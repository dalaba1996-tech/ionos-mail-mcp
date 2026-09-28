from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import uvicorn
import os
import imaplib
import email
import hmac
import tempfile
import uuid
import json
from pathlib import Path
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
MCP_API_KEY = os.environ.get("MCP_API_KEY")
UPLOAD_DIR = Path(tempfile.gettempdir()) / "ionos_mcp_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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
    f"ID: {message_id.decode()}\n"
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
    f"ID: {message_id.decode()}\n"
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
def read_email(message_id: str) -> str:
    """Lit le contenu complet d'un email IONOS à partir de son identifiant."""

    mail = connect_imap()

    try:
        mail.select("INBOX", readonly=True)

        status, msg_data = mail.fetch(message_id, "(RFC822)")

        if status != "OK":
            return "Impossible de récupérer cet email."

        raw_email = next(
            (
                item[1]
                for item in msg_data
                if isinstance(item, tuple)
            ),
            None,
        )

        if not raw_email:
            return "Email introuvable."

        msg = email.message_from_bytes(raw_email)

        sender = decode_text(msg.get("From"))
        recipient = decode_text(msg.get("To"))
        subject = decode_text(msg.get("Subject"))
        date = msg.get("Date", "")

        body = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(
                    part.get("Content-Disposition", "")
                ).lower()

                # On ignore les pièces jointes pour l'instant
                if "attachment" in disposition:
                    continue

                if content_type == "text/plain":
                    payload = part.get_payload(decode=True)

                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(
                            charset,
                            errors="replace"
                        )
                        break

        else:
            payload = msg.get_payload(decode=True)

            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(
                    charset,
                    errors="replace"
                )

        if not body.strip():
            body = (
                "Le message ne contient pas de version texte "
                "directement lisible."
            )

        return (
            f"De: {sender}\n"
            f"À: {recipient}\n"
            f"Objet: {subject}\n"
            f"Date: {date}\n\n"
            f"Contenu:\n{body.strip()}"
        )

    finally:
        try:
            mail.logout()
        except Exception:
            pass
            
@mcp.tool()
def list_attachments(message_id: str) -> str:
    """Liste les pièces jointes présentes dans un email IONOS."""

    mail = connect_imap()

    try:
        mail.select("INBOX", readonly=True)

        status, msg_data = mail.fetch(message_id, "(RFC822)")

        if status != "OK":
            return "Impossible de récupérer cet email."

        raw_email = next(
            (
                item[1]
                for item in msg_data
                if isinstance(item, tuple)
            ),
            None,
        )

        if not raw_email:
            return "Email introuvable."

        msg = email.message_from_bytes(raw_email)

        attachments = []

        for index, part in enumerate(msg.walk()):
            filename = part.get_filename()

            if filename:
                filename = decode_text(filename)

                attachments.append(
                    f"ID pièce jointe: {index}\n"
                    f"Nom: {filename}\n"
                    f"Type: {part.get_content_type()}\n"
                    f"Taille: "
                    f"{len(part.get_payload(decode=True) or b'')} octets"
                )

        if not attachments:
            return "Cet email ne contient aucune pièce jointe."

        return "\n\n---\n\n".join(attachments)

    finally:
        try:
            mail.logout()
        except Exception:
            pass
@mcp.tool()
def read_attachment(message_id: str, attachment_id: int) -> str:
    """Lit le contenu d'une pièce jointe PDF, DOCX, XLSX, CSV ou TXT."""

    import io
    import csv
    from pypdf import PdfReader
    from docx import Document
    from openpyxl import load_workbook

    mail = connect_imap()

    try:
        mail.select("INBOX", readonly=True)
        status, msg_data = mail.fetch(message_id, "(RFC822)")

        if status != "OK":
            return "Impossible de récupérer cet email."

        raw_email = next(
            (item[1] for item in msg_data if isinstance(item, tuple)),
            None,
        )

        if not raw_email:
            return "Email introuvable."

        msg = email.message_from_bytes(raw_email)

        parts = list(msg.walk())

        if attachment_id < 0 or attachment_id >= len(parts):
            return "Identifiant de pièce jointe invalide."

        part = parts[attachment_id]
        filename = part.get_filename()

        if not filename:
            return "Cette partie du message n'est pas une pièce jointe."

        filename = decode_text(filename)
        data = part.get_payload(decode=True)

        if not data:
            return "La pièce jointe est vide."

        # Limite de sécurité : 10 Mo
        if len(data) > 10 * 1024 * 1024:
            return "Pièce jointe trop volumineuse (limite : 10 Mo)."

        extension = filename.lower().rsplit(".", 1)[-1]

        if extension == "pdf":
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join(
                page.extract_text() or ""
                for page in reader.pages
            )

        elif extension == "docx":
            document = Document(io.BytesIO(data))
            text = "\n".join(
                paragraph.text
                for paragraph in document.paragraphs
            )

        elif extension == "xlsx":
            workbook = load_workbook(
                io.BytesIO(data),
                read_only=True,
                data_only=True
            )

            output = []

            for sheet in workbook.worksheets:
                output.append(f"Feuille: {sheet.title}")

                for row in sheet.iter_rows(values_only=True):
                    output.append(
                        " | ".join(
                            "" if value is None else str(value)
                            for value in row
                        )
                    )

            text = "\n".join(output)

        elif extension == "csv":
            decoded = data.decode("utf-8-sig", errors="replace")
            rows = csv.reader(io.StringIO(decoded))

            text = "\n".join(
                " | ".join(row)
                for row in rows
            )

        elif extension in ("txt", "md"):
            text = data.decode("utf-8", errors="replace")

        else:
            return (
                f"Format non pris en charge : {filename}. "
                "Formats acceptés : PDF, DOCX, XLSX, CSV, TXT et MD."
            )

        # Évite d'envoyer une quantité énorme de texte à Claude
        max_chars = 100_000

        if len(text) > max_chars:
            text = (
                text[:max_chars]
                + "\n\n[Contenu tronqué après 100 000 caractères]"
            )

        return (
            f"Fichier: {filename}\n\n"
            f"{text.strip() or '[Aucun texte extractible]'}"
        )

    except Exception as exc:
        return f"Impossible de lire la pièce jointe : {type(exc).__name__}"

    finally:
        try:
            mail.logout()
        except Exception:
            pass
@mcp.tool()
def create_draft(
    to: str,
    subject: str,
    body: str,
    cc: str = ""
) -> str:
    """Crée un brouillon dans la boîte IONOS sans envoyer l'email."""

    from email.message import EmailMessage
    from email.utils import formatdate
    import time

    mail = connect_imap()

    try:
        # Cherche le dossier Brouillons disponible sur la boîte IONOS
        status, folders = mail.list()

        if status != "OK":
            return "Impossible d'accéder aux dossiers de la boîte mail."

        draft_folder = None

        for folder in folders:
            folder_text = folder.decode(errors="replace")

            # IONOS peut utiliser différents noms selon la configuration
            if (
                "\\Drafts" in folder_text
                or '"Drafts"' in folder_text
                or '"Brouillons"' in folder_text
            ):
                # Le nom du dossier est généralement le dernier élément
                draft_folder = folder_text.split(' "/" ')[-1].strip('"')
                break

        if not draft_folder:
            return (
                "Impossible de trouver automatiquement le dossier "
                "Brouillons/Drafts de cette boîte IONOS."
            )

        msg = EmailMessage()

        msg["From"] = EMAIL_USER
        msg["To"] = to

        if cc.strip():
            msg["Cc"] = cc

        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)

        msg.set_content(body)

        status, _ = mail.append(
            draft_folder,
            "\\Draft",
            imaplib.Time2Internaldate(time.time()),
            msg.as_bytes()
        )

        if status != "OK":
            return "IONOS n'a pas pu enregistrer le brouillon."

        return (
            "Brouillon créé avec succès.\n"
            f"À: {to}\n"
            f"Objet: {subject}\n"
            "Le message n'a PAS été envoyé."
        )

    except Exception as exc:
        return (
            "Impossible de créer le brouillon : "
            f"{type(exc).__name__}"
        )

    finally:
        try:
            mail.logout()
        except Exception:
            pass

@mcp.tool()
def create_draft_with_attachments(
    to: str,
    subject: str,
    body: str,
    source_message_id: str,
    attachment_ids: list[int],
    cc: str = ""
) -> str:
    """
    Crée un brouillon IONOS avec une ou plusieurs pièces jointes
    provenant d'un même email existant. Le message n'est pas envoyé.
    """

    from email.message import EmailMessage
    from email.utils import formatdate
    import mimetypes
    import time

    mail = connect_imap()

    try:
        # Récupération du mail source
        mail.select("INBOX", readonly=True)

        status, msg_data = mail.fetch(
            source_message_id,
            "(RFC822)"
        )

        if status != "OK":
            return "Impossible de récupérer l'email source."

        raw_email = next(
            (
                item[1]
                for item in msg_data
                if isinstance(item, tuple)
            ),
            None,
        )

        if not raw_email:
            return "Email source introuvable."

        source_msg = email.message_from_bytes(raw_email)
        parts = list(source_msg.walk())

        if not attachment_ids:
            return "Aucune pièce jointe sélectionnée."

        # Construction du brouillon
        msg = EmailMessage()

        msg["From"] = EMAIL_USER
        msg["To"] = to

        if cc.strip():
            msg["Cc"] = cc

        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg.set_content(body)

        attached_files = []
        total_size = 0

        for attachment_id in attachment_ids:

            if attachment_id < 0 or attachment_id >= len(parts):
                return (
                    f"Identifiant de pièce jointe invalide : "
                    f"{attachment_id}"
                )

            part = parts[attachment_id]
            filename = part.get_filename()

            if not filename:
                return (
                    f"La partie {attachment_id} n'est pas "
                    "une pièce jointe."
                )

            filename = decode_text(filename)
            attachment_data = part.get_payload(decode=True)

            if not attachment_data:
                return f"La pièce jointe {filename} est vide."

            total_size += len(attachment_data)

            # Limite totale : 20 Mo
            if total_size > 20 * 1024 * 1024:
                return (
                    "Les pièces jointes dépassent la limite "
                    "totale de 20 Mo."
                )

            content_type = (
                part.get_content_type()
                or mimetypes.guess_type(filename)[0]
                or "application/octet-stream"
            )

            maintype, subtype = content_type.split("/", 1)

            msg.add_attachment(
                attachment_data,
                maintype=maintype,
                subtype=subtype,
                filename=filename
            )

            attached_files.append(filename)

        # Recherche du dossier Brouillons
        status, folders = mail.list()

        if status != "OK":
            return "Impossible d'accéder aux dossiers IONOS."

        draft_folder = None

        for folder in folders:
            folder_text = folder.decode(errors="replace")

            if (
                "\\Drafts" in folder_text
                or '"Drafts"' in folder_text
                or '"Brouillons"' in folder_text
            ):
                draft_folder = (
                    folder_text
                    .split(' "/" ')[-1]
                    .strip('"')
                )
                break

        if not draft_folder:
            return "Dossier Brouillons/Drafts introuvable."

        # Enregistrement du brouillon
        status, _ = mail.append(
            draft_folder,
            "\\Draft",
            imaplib.Time2Internaldate(time.time()),
            msg.as_bytes()
        )

        if status != "OK":
            return "IONOS n'a pas pu enregistrer le brouillon."

        files_list = "\n".join(
            f"- {filename}"
            for filename in attached_files
        )

        return (
            "Brouillon créé avec succès.\n"
            f"À: {to}\n"
            f"Objet: {subject}\n"
            f"Pièces jointes ({len(attached_files)}):\n"
            f"{files_list}\n\n"
            "Le message n'a PAS été envoyé."
        )

    except Exception as exc:
        return (
            "Impossible de créer le brouillon avec pièces jointes : "
            f"{type(exc).__name__}"
        )

    finally:
        try:
            mail.logout()
        except Exception:
            pass


@mcp.tool()
def start_upload(
    filename: str,
    mime_type: str,
    total_size: int,
    sha256: str
) -> str:
    """
    Démarre l'envoi sécurisé d'un fichier en plusieurs morceaux.
    Retourne un upload_id à utiliser pour les morceaux suivants.
    """

    # Limite totale : 20 Mo
    max_size = 20 * 1024 * 1024

    if total_size <= 0:
        return "Erreur : taille de fichier invalide."

    if total_size > max_size:
        return "Erreur : fichier trop volumineux (limite : 20 Mo)."

    # Évite qu'un nom de fichier puisse écrire ailleurs sur le serveur
    safe_filename = Path(filename).name

    if not safe_filename:
        return "Erreur : nom de fichier invalide."

    expected_hash = sha256.lower().strip()

    if (
        len(expected_hash) != 64
        or any(c not in "0123456789abcdef" for c in expected_hash)
    ):
        return "Erreur : SHA-256 invalide."

    upload_id = uuid.uuid4().hex

    session_dir = UPLOAD_DIR / upload_id
    session_dir.mkdir(parents=True, exist_ok=False)

    metadata = {
        "filename": safe_filename,
        "mime_type": mime_type or "application/octet-stream",
        "total_size": total_size,
        "sha256": expected_hash,
        "next_chunk": 0,
    }

    with open(session_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f)

    # Fichier vide qui recevra progressivement les données
    (session_dir / "data.bin").touch()

    return (
        "Upload initialisé.\n"
        f"upload_id: {upload_id}\n"
        "Commence avec chunk_index: 0."
    )
            
@mcp.tool()
def append_chunk(
    upload_id: str,
    chunk_index: int,
    data_base64: str
) -> str:
    """
    Ajoute un morceau encodé en base64 à un upload en cours.
    Les morceaux doivent être envoyés dans l'ordre.
    """

    import base64
    import binascii

    # Validation de l'identifiant
    if (
        len(upload_id) != 32
        or any(c not in "0123456789abcdef" for c in upload_id)
    ):
        return "Erreur : upload_id invalide."

    session_dir = UPLOAD_DIR / upload_id
    metadata_path = session_dir / "metadata.json"
    data_path = session_dir / "data.bin"

    if not metadata_path.exists() or not data_path.exists():
        return "Erreur : session d'upload introuvable ou expirée."

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        expected_chunk = metadata.get("next_chunk", 0)

        if chunk_index != expected_chunk:
            return (
                "Erreur : mauvais ordre des morceaux. "
                f"Chunk attendu : {expected_chunk}."
            )

        # Limite par morceau : 32 Ko de données encodées
        if len(data_base64) > 50_000:
            return (
                "Erreur : morceau trop volumineux. "
                "Utilise des chunks plus petits."
            )

        try:
            chunk_data = base64.b64decode(
                data_base64,
                validate=True
            )
        except (binascii.Error, ValueError):
            return "Erreur : données base64 invalides."

        if not chunk_data:
            return "Erreur : morceau vide."

        current_size = data_path.stat().st_size
        new_size = current_size + len(chunk_data)

        if new_size > metadata["total_size"]:
            return (
                "Erreur : les données reçues dépassent "
                "la taille annoncée du fichier."
            )

        with open(data_path, "ab") as f:
            f.write(chunk_data)

        metadata["next_chunk"] = expected_chunk + 1

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f)

        return (
            f"Chunk {chunk_index} reçu correctement.\n"
            f"Octets reçus : {new_size}/{metadata['total_size']}\n"
            f"Prochain chunk : {metadata['next_chunk']}"
        )

    except Exception as exc:
        return (
            "Erreur pendant la réception du morceau : "
            f"{type(exc).__name__}"
        )

@mcp.tool()
def finish_upload(upload_id: str) -> str:
    """
    Termine un upload et vérifie la taille ainsi que le SHA-256
    avant d'autoriser l'utilisation du fichier.
    """

    import hashlib

    if (
        len(upload_id) != 32
        or any(c not in "0123456789abcdef" for c in upload_id)
    ):
        return "Erreur : upload_id invalide."

    session_dir = UPLOAD_DIR / upload_id
    metadata_path = session_dir / "metadata.json"
    data_path = session_dir / "data.bin"

    if not metadata_path.exists() or not data_path.exists():
        return "Erreur : session d'upload introuvable ou expirée."

    try:
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        actual_size = data_path.stat().st_size
        expected_size = metadata["total_size"]

        # Vérification de la taille
        if actual_size != expected_size:
            return (
                "Upload incomplet.\n"
                f"Taille attendue : {expected_size} octets\n"
                f"Taille reçue : {actual_size} octets\n"
                f"Prochain chunk attendu : "
                f"{metadata.get('next_chunk', 0)}"
            )

        # Calcul SHA-256 du fichier réellement reconstruit
        sha256 = hashlib.sha256()

        with open(data_path, "rb") as f:
            while True:
                block = f.read(1024 * 1024)

                if not block:
                    break

                sha256.update(block)

        actual_hash = sha256.hexdigest()
        expected_hash = metadata["sha256"]

        if not hmac.compare_digest(actual_hash, expected_hash):
            return (
                "ERREUR : contrôle d'intégrité échoué.\n"
                "Le fichier reconstruit ne correspond pas "
                "au fichier original.\n"
                "Le fichier ne doit pas être utilisé."
            )

        # Le fichier est maintenant considéré comme validé
        metadata["validated"] = True
        metadata["actual_sha256"] = actual_hash

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f)

        return (
            "Upload terminé et vérifié avec succès.\n"
            f"upload_id: {upload_id}\n"
            f"Fichier: {metadata['filename']}\n"
            f"Taille: {actual_size} octets\n"
            f"SHA-256 vérifié: {actual_hash}\n"
            "Le fichier peut maintenant être utilisé "
            "comme pièce jointe."
        )

    except Exception as exc:
        return (
            "Erreur pendant la validation de l'upload : "
            f"{type(exc).__name__}"
        )
        
@mcp.tool()
def create_draft_with_uploaded_attachments(
    to: str,
    subject: str,
    body: str,
    upload_ids: list[str],
    cc: str = ""
) -> str:
    """
    Crée un brouillon IONOS avec un ou plusieurs fichiers
    précédemment uploadés et validés. N'envoie jamais l'email.
    """

    from email.message import EmailMessage
    from email.utils import formatdate
    import mimetypes
    import time

    if not upload_ids:
        return "Erreur : aucun fichier fourni."

    mail = connect_imap()

    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_USER
        msg["To"] = to

        if cc.strip():
            msg["Cc"] = cc

        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg.set_content(body)

        attached_files = []
        total_size = 0

        for upload_id in upload_ids:

            if (
                len(upload_id) != 32
                or any(c not in "0123456789abcdef" for c in upload_id)
            ):
                return f"Erreur : upload_id invalide : {upload_id}"

            session_dir = UPLOAD_DIR / upload_id
            metadata_path = session_dir / "metadata.json"
            data_path = session_dir / "data.bin"

            if not metadata_path.exists() or not data_path.exists():
                return (
                    "Erreur : fichier uploadé introuvable "
                    f"ou expiré : {upload_id}"
                )

            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # Refus absolu d'une PJ qui n'a pas passé finish_upload
            if metadata.get("validated") is not True:
                return (
                    f"Erreur : {metadata.get('filename', upload_id)} "
                    "n'a pas été validé par finish_upload."
                )

            data = data_path.read_bytes()

            # Nouvelle vérification avant création du brouillon
            import hashlib

            actual_hash = hashlib.sha256(data).hexdigest()

            if not hmac.compare_digest(
                actual_hash,
                metadata["sha256"]
            ):
                return (
                    f"Erreur d'intégrité : "
                    f"{metadata['filename']}."
                )

            total_size += len(data)

            # Limite cumulée
            if total_size > 20 * 1024 * 1024:
                return (
                    "Erreur : les pièces jointes dépassent "
                    "20 Mo au total."
                )

            filename = metadata["filename"]
            content_type = metadata.get(
                "mime_type",
                "application/octet-stream"
            )

            # Sécurité si le MIME fourni est incorrect
            if "/" not in content_type:
                content_type = (
                    mimetypes.guess_type(filename)[0]
                    or "application/octet-stream"
                )

            maintype, subtype = content_type.split("/", 1)

            msg.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype,
                filename=filename
            )

            attached_files.append(filename)

        # Recherche du dossier Brouillons
        status, folders = mail.list()

        if status != "OK":
            return "Impossible d'accéder aux dossiers IONOS."

        draft_folder = None

        for folder in folders:
            folder_text = folder.decode(errors="replace")

            if (
                "\\Drafts" in folder_text
                or '"Drafts"' in folder_text
                or '"Brouillons"' in folder_text
            ):
                draft_folder = (
                    folder_text
                    .split(' "/" ')[-1]
                    .strip('"')
                )
                break

        if not draft_folder:
            return "Dossier Brouillons/Drafts introuvable."

        status, _ = mail.append(
            draft_folder,
            "\\Draft",
            imaplib.Time2Internaldate(time.time()),
            msg.as_bytes()
        )

        if status != "OK":
            return "IONOS n'a pas pu enregistrer le brouillon."

        files_list = "\n".join(
            f"- {filename}"
            for filename in attached_files
        )

        return (
            "Brouillon créé avec succès.\n"
            f"À: {to}\n"
            f"Objet: {subject}\n"
            f"Pièces jointes ({len(attached_files)}):\n"
            f"{files_list}\n\n"
            "Le message n'a PAS été envoyé."
        )

    except Exception as exc:
        return (
            "Impossible de créer le brouillon : "
            f"{type(exc).__name__}"
        )

    finally:
        try:
            mail.logout()
        except Exception:
            pass
            
class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/mcp"):
            provided_key = request.headers.get("X-API-Key", "")

            if not MCP_API_KEY or not hmac.compare_digest(
                provided_key,
                MCP_API_KEY
            ):
                return JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401
                )

        return await call_next(request)


app = mcp.streamable_http_app()
app.add_middleware(APIKeyMiddleware)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
