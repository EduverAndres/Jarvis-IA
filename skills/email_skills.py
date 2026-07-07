"""Correo (Gmail) vía IMAP/SMTP con contraseña de aplicación — no requiere
crear un proyecto OAuth en Google Cloud, solo tener verificación en dos pasos
activada y generar una "contraseña de aplicación" en la cuenta de Google.

- check_new_emails(): usado por el sondeo en segundo plano (ui/window.py) para
  avisar proactivamente — solo devuelve correos con UID mayor al último ya
  avisado (data/email_state.json), así no repite el mismo aviso en cada
  sondeo aunque el correo siga "no leído" en el servidor.
- get_unread_summary(): skill bajo demanda ("¿tengo correos nuevos?") — cuenta
  TODOS los no leídos actuales, sin tocar el estado de avisos ya dados.
- send_email(): requiere confirm_fn (igual que delete_item) — el envío de un
  correo no se deshace, así que siempre pasa por el modal de confirmación.
- archive_email(): quita la etiqueta "Recibidos" (extensión X-GM-LABELS,
  específica de Gmail) — el mensaje sigue existiendo en "Todos".
"""

import imaplib
import json
import os
import smtplib
from email.header import decode_header
from email.mime.text import MIMEText

_IMAP_HOST = "imap.gmail.com"
_SMTP_HOST = "smtp.gmail.com"

_STATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "email_state.json"
)


def _address() -> str:
    return os.environ.get("GMAIL_ADDRESS", "")


def _app_password() -> str:
    return os.environ.get("GMAIL_APP_PASSWORD", "")


def _configured() -> bool:
    return bool(_address() and _app_password())


def _not_configured_msg() -> str:
    return ("Falta configurar el correo: agrega GMAIL_ADDRESS y GMAIL_APP_PASSWORD "
            "en tu archivo .env.")


def _load_state() -> dict:
    try:
        with open(_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict):
    os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _decode(value: str) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(text)
    return "".join(out)


def _connect_imap() -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(_IMAP_HOST)
    imap.login(_address(), _app_password())
    imap.select("INBOX")
    return imap


def _search_uids(imap: imaplib.IMAP4_SSL, *criteria) -> list[int]:
    typ, data = imap.uid("search", None, *criteria)
    if typ != "OK" or not data or not data[0]:
        return []
    return [int(u) for u in data[0].split()]


def _fetch_headers(imap: imaplib.IMAP4_SSL, uid: int) -> dict:
    typ, data = imap.uid("fetch", str(uid), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
    from_, subject = "(remitente desconocido)", "(sin asunto)"
    if typ == "OK" and data and data[0]:
        raw = data[0][1].decode("utf-8", errors="ignore")
        for line in raw.splitlines():
            if line.lower().startswith("from:"):
                from_ = _decode(line[5:].strip())
            elif line.lower().startswith("subject:"):
                subject = _decode(line[8:].strip()) or subject
    return {"from": from_, "subject": subject}


def check_new_emails() -> list[dict]:
    """Correos no leídos con UID mayor al último ya avisado. Actualiza el
    estado para no repetir el mismo aviso en el próximo sondeo."""
    if not _configured():
        return []
    state = _load_state()
    last_uid = state.get("last_uid", 0)
    try:
        imap = _connect_imap()
        uids = sorted(u for u in _search_uids(imap, "UNSEEN") if u > last_uid)
        results = [_fetch_headers(imap, uid) for uid in uids]
        if uids:
            state["last_uid"] = max(uids)
            _save_state(state)
        imap.logout()
        return results
    except Exception:
        return []


def get_unread_summary() -> str:
    if not _configured():
        return _not_configured_msg()
    try:
        imap = _connect_imap()
        uids = _search_uids(imap, "UNSEEN")
        if not uids:
            imap.logout()
            return "No tienes correos nuevos sin leer."
        preview = [_fetch_headers(imap, uid) for uid in uids[-5:][::-1]]
        imap.logout()
        total = len(uids)
        header = f"Tienes {total} correo{'s' if total != 1 else ''} sin leer"
        lines = "\n".join(f"- {h['from']}: {h['subject']}" for h in preview)
        return f"{header}:\n{lines}"
    except imaplib.IMAP4.error as e:
        return f"No pude conectarme a Gmail — revisa la contraseña de aplicación. ({e})"
    except Exception as e:
        return f"No pude revisar el correo: {e}"


def send_email(to: str, subject: str, body: str, confirm_fn=None) -> str:
    if not _configured():
        return _not_configured_msg()
    if confirm_fn is None:
        raise PermissionError(
            "Envío de correo bloqueado: se requiere confirmación del usuario antes de enviar."
        )
    summary = f"Para: {to}\nAsunto: {subject}\n\n{body}"
    if not confirm_fn(summary):
        return "Envío cancelado por el usuario."

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = _address()
    msg["To"] = to
    try:
        with smtplib.SMTP_SSL(_SMTP_HOST, 465) as smtp:
            smtp.login(_address(), _app_password())
            smtp.send_message(msg)
        return f"Correo enviado a {to}."
    except Exception as e:
        return f"No pude enviar el correo: {e}"


def archive_email(which: str = "") -> str:
    """Archiva el correo más reciente que coincida con `which` (remitente o
    asunto), o el más reciente de todos si no se especifica nada."""
    if not _configured():
        return _not_configured_msg()
    try:
        imap = _connect_imap()
        which = (which or "").strip()
        if which:
            uids = _search_uids(imap, "OR", "FROM", f'"{which}"', "SUBJECT", f'"{which}"')
        else:
            uids = _search_uids(imap, "ALL")
        if not uids:
            imap.logout()
            return (f'No encontré ningún correo que coincida con "{which}".' if which
                     else "No hay correos en la bandeja de entrada.")
        uid = uids[-1]
        hdr = _fetch_headers(imap, uid)
        imap.uid("store", str(uid), "-X-GM-LABELS", "(\\Inbox)")
        imap.logout()
        return f"Archivé el correo de {hdr['from']} ('{hdr['subject']}')."
    except Exception as e:
        return f"No pude archivar el correo: {e}"
