import base64
import hashlib
import os
import re
import shutil
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime, getaddresses
from typing import List, Dict

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

SERVICE_ACCOUNT_FILE = os.getenv("SERVICE_ACCOUNT_FILE", "../../../creds/service-account.json")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

BASE_DIR = "storage"
CONFIG_DIR = "config"


def _mailbox_slug(mailbox: str) -> str:
    return mailbox.split("@")[0]


def _get_header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


def _hash_message_id(message_id: str) -> str:
    return hashlib.sha256(message_id.encode()).hexdigest()


_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def _decode_filename(part):
    filename = part.get("filename")
    if not filename:
        return None
    # A real CA ANZ attachment name containing a corrupted en-dash (showing
    # up as a literal "?") crashed os.open on Windows, which forbids
    # <>:"/\|?* in filenames — sanitized here so a single oddly-named
    # attachment can't take down the whole email's processing.
    return _ILLEGAL_FILENAME_CHARS.sub("_", filename)


def _walk_parts(parts, acc=None):
    if acc is None:
        acc = []
    for p in parts or []:
        acc.append(p)
        if p.get("parts"):
            _walk_parts(p["parts"], acc)
    return acc


def _extract_body_text(parts):
    # Some ART correspondence (e.g. the "documents received" confirmation)
    # has no PDF attachment at all — everything needed lives only in the
    # email body, so it's carried through as plain text alongside the usual
    # attachment paths, for anything that wants to extract from it.
    for part in _walk_parts(parts):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return None


_FORWARDED_TO_RE = re.compile(
    r"---------- ?Forwarded message ?---------.*?\nTo:\s*(.*?)\n\s*\n",
    re.DOTALL,
)


def _extract_forwarded_recipients(body_text):
    # Skills Assessment correspondence (VETASSESS/EA) is often addressed to
    # the client directly by the authority, then forwarded *internally* by
    # staff to a consultant — so the Gmail message's own "To" header is the
    # staff member, not the client, and the real client address only shows
    # up inside the quoted "---------- Forwarded message ---------" block.
    # Without this, Agentcis recipient-matching silently tries the wrong
    # (internal) address and fails.
    if not body_text:
        return []

    match = _FORWARDED_TO_RE.search(body_text)
    if not match:
        return []

    # Not using getaddresses() here: its RFC2822 parser returns garbage
    # ('', '') when the display name is itself a bare, unquoted email
    # address ("x@y.com <x@y.com>") — a real pattern Gmail produces when a
    # sender has no display name set, and exactly what shows up here. A
    # direct regex for anything email-shaped is simpler and more robust.
    return [addr.lower() for addr in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", match.group(1))]


class GmailClient:
    """
    Gmail API replacement for ImapClient, kept as a drop-in: same public
    interface (connect/fetch_new_emails/close) and same email-dict shape
    (message_id, subject, date, recipients, cc, attachments, folder_path)
    so the rest of the pipeline (processor, business_rules, field_mapper,
    agentcis_handler) needs no changes.
    """

    def __init__(self, mailbox: str):
        self.mailbox = mailbox
        self.slug = _mailbox_slug(mailbox)

        self.base_dir = os.path.join(BASE_DIR, self.slug)
        self.config_dir = os.path.join(CONFIG_DIR, self.slug)
        self.processed_file = os.path.join(self.config_dir, "processed_ids.txt")
        self.last_run_file = os.path.join(self.config_dir, "last_run.txt")

        os.makedirs(self.base_dir, exist_ok=True)
        os.makedirs(self.config_dir, exist_ok=True)

        self.service = None

    def connect(self):
        print(f"Connecting to Gmail API as {self.mailbox}...")

        base_creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=GMAIL_SCOPES
        )
        creds = base_creds.with_subject(self.mailbox)
        self.service = build("gmail", "v1", credentials=creds)

        print(f"Connected as {self.mailbox}")

    # ---------------- idempotency state ---------------- #

    def _load_processed_ids(self):
        if not os.path.exists(self.processed_file):
            return set()
        with open(self.processed_file, "r") as f:
            return set(line.strip() for line in f if line.strip())

    def _append_processed_id(self, msg_hash):
        with open(self.processed_file, "a") as f:
            f.write(msg_hash + "\n")

    def _load_last_run(self):
        if not os.path.exists(self.last_run_file):
            return None
        with open(self.last_run_file, "r") as f:
            content = f.read().strip()
        if not content:
            return None
        try:
            return datetime.fromisoformat(content)
        except ValueError:
            return None

    def _save_last_run(self, dt):
        with open(self.last_run_file, "w") as f:
            f.write(dt.isoformat())

    # ---------------- fetch ---------------- #

    def fetch_new_emails(self, custom_start=None, custom_end=None) -> List[Dict]:

        processed_ids = self._load_processed_ids()
        last_run = self._load_last_run()

        if custom_start:
            after_dt = custom_start
            print(f"Custom mode — searching after {after_dt.isoformat()}")
        elif last_run:
            after_dt = last_run
            print(f"Searching emails after {after_dt.isoformat()}")
        else:
            after_dt = datetime.now(timezone.utc) - timedelta(days=2)
            print(f"First run — processing emails after {after_dt.isoformat()}")

        after_epoch = int(after_dt.timestamp())
        query = f"in:sent after:{after_epoch}"

        message_ids = []
        page_token = None
        while True:
            res = self.service.users().messages().list(
                userId="me", q=query, maxResults=500, pageToken=page_token
            ).execute()
            message_ids.extend(m["id"] for m in res.get("messages", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break

        results = []
        processed_count = 0

        for msg_id in message_ids:
            full = self.service.users().messages().get(
                userId="me", id=msg_id, format="full"
            ).execute()

            headers = full["payload"]["headers"]
            message_id_header = _get_header(headers, "Message-ID")
            if not message_id_header:
                continue

            msg_hash = _hash_message_id(message_id_header)

            if not (custom_start or custom_end):
                if msg_hash in processed_ids:
                    continue

            internal_dt = datetime.fromtimestamp(
                int(full["internalDate"]) / 1000, tz=timezone.utc
            )

            if custom_start or custom_end:
                local_dt = internal_dt.astimezone().replace(tzinfo=None)
                if custom_start and local_dt < custom_start:
                    continue
                if custom_end and local_dt > custom_end:
                    continue
            else:
                if last_run and internal_dt <= last_run:
                    continue

            processed_count += 1

            email_dir = os.path.join(self.base_dir, f"email_{processed_count}")
            attach_dir = os.path.join(email_dir, "attachments")
            # email_N folders are numbered by position within a run, not by
            # message identity — a later run's email_15 can land on a
            # different message than an earlier run's email_15. Without
            # clearing it first, a message with no attachments of its own
            # (e.g. "Application Cancelled") can inherit stale PDFs left
            # over from whatever email previously occupied that slot,
            # silently merging an unrelated case's data into this one.
            # Confirmed live: a leftover "MSA CDR Outcome Letter" PDF from
            # a prior run caused a second, spurious Outcomes row.
            if os.path.exists(email_dir):
                shutil.rmtree(email_dir)
            os.makedirs(attach_dir, exist_ok=True)

            attachments = []
            for part in _walk_parts(full["payload"].get("parts")):
                filename = _decode_filename(part)
                if not filename:
                    continue

                body = part.get("body", {})
                attachment_id = body.get("attachmentId")
                if not attachment_id:
                    continue

                att = self.service.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=attachment_id
                ).execute()

                data = base64.urlsafe_b64decode(att["data"])
                filepath = os.path.join(attach_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(data)

                attachments.append(filepath)

            to_field = _get_header(headers, "To") or ""
            parsed_to = getaddresses([to_field])
            recipients = [addr.lower() for name, addr in parsed_to if addr]

            cc_field = _get_header(headers, "Cc") or ""
            parsed_cc = getaddresses([cc_field])
            cc_list = [addr.lower() for name, addr in parsed_cc if addr]

            body_text = _extract_body_text(full["payload"].get("parts"))

            # Merge in any recipient only visible inside a quoted "Forwarded
            # message" block (see _extract_forwarded_recipients) — the real
            # client address for internally-forwarded Skills Assessment
            # correspondence lives there, not in this message's own "To".
            for addr in _extract_forwarded_recipients(body_text):
                if addr not in recipients:
                    recipients.append(addr)

            results.append({
                "message_id": message_id_header,
                "message_hash": msg_hash,
                "subject": _get_header(headers, "Subject") or "",
                "date": _get_header(headers, "Date"),
                "recipients": recipients,
                "cc": cc_list,
                "attachments": attachments,
                "folder_path": email_dir,
                "body_text": body_text,
            })

            if not (custom_start or custom_end):
                self._append_processed_id(msg_hash)

        if not (custom_start or custom_end):
            self._save_last_run(datetime.now(timezone.utc))

        print(f"{len(results)} new emails fetched from {self.mailbox}")
        return results

    def close(self):
        self.service = None
