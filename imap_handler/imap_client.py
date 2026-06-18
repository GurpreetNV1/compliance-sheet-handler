import imaplib
import email
import os
import hashlib
from email.header import decode_header
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime, getaddresses
from typing import List, Dict
from dotenv import load_dotenv

load_dotenv()
email_id = os.getenv("EMAIL_ACCOUNT")
password = os.getenv("PASSWORD")
# ================= CONFIG =================
IMAP_SERVER = "imap.gmail.com"
EMAIL_ACCOUNT = email_id
PASSWORD = password
# MAILBOX = "INBOX"  # for Inbox
MAILBOX = '"[Gmail]/Sent Mail"' # For sent mail
BASE_DIR = "storage"
CONFIG_DIR = "config"
# =========================================

PROCESSED_FILE = os.path.join(CONFIG_DIR, "processed_ids.txt")
LAST_RUN_FILE = os.path.join(CONFIG_DIR, "last_run.txt")

os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)


def decode_value(value):
    if not value:
        return ""
    decoded, enc = decode_header(value)[0]
    if isinstance(decoded, bytes):
        return decoded.decode(enc or "utf-8", errors="ignore")
    return decoded


def hash_message_id(message_id):
    return hashlib.sha256(message_id.encode()).hexdigest()


def load_processed_ids():
    if not os.path.exists(PROCESSED_FILE):
        return set()
    with open(PROCESSED_FILE, "r") as f:
        return set(line.strip() for line in f if line.strip())


def append_processed_id(msg_id_hash):
    with open(PROCESSED_FILE, "a") as f:
        f.write(msg_id_hash + "\n")


def load_last_run():
    if not os.path.exists(LAST_RUN_FILE):
        return None

    with open(LAST_RUN_FILE, "r") as f:
        content = f.read().strip()

    if not content:
        return None

    try:
        return datetime.fromisoformat(content)
    except ValueError:
        return None


def save_last_run(dt):
    with open(LAST_RUN_FILE, "w") as f:
        f.write(dt.isoformat())


# ================= CLASS =================


class ImapClient:

    def __init__(self):
        self.mail = None

    def connect(self):
        print("Connecting to IMAP...")
        self.mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        self.mail.login(EMAIL_ACCOUNT, PASSWORD)

        status, _ = self.mail.select(MAILBOX)
        if status != "OK":
            raise RuntimeError(f"Failed to select mailbox: {MAILBOX}")

        print(f"Selected mailbox: {MAILBOX}")

    def fetch_new_emails(self, custom_start=None, custom_end=None) -> List[Dict]:

        processed_ids = load_processed_ids()
        last_run = load_last_run()

    # Decide Search Window
        if custom_start:
            since_date = custom_start.strftime("%d-%b-%Y")
            search_criteria = f'(SINCE {since_date})'
            print(f"Custom mode — searching SINCE {since_date}")

        elif last_run:
            since_date = last_run.strftime("%d-%b-%Y")
            search_criteria = f'(SINCE {since_date})'
            print(f"Searching emails SINCE {since_date}")

        else:
            first_run_time = datetime.now(timezone.utc) - timedelta(days=2)
            since_date = first_run_time.strftime("%d-%b-%Y")
            search_criteria = f'(SINCE {since_date})'
            print(f"First run — processing emails SINCE {since_date}")

        status, messages = self.mail.search(None, search_criteria)
        if status != "OK":
            raise RuntimeError("Search failed")

        email_ids = messages[0].split()

        results = []
        processed_count = 0

        for eid in email_ids:

            _, header_data = self.mail.fetch(eid, "(BODY.PEEK[HEADER])")
            msg_header = email.message_from_bytes(header_data[0][1])

            message_id = msg_header.get("Message-ID")
            if not message_id:
                continue

            msg_hash = hash_message_id(message_id)

            # if msg_hash in processed_ids:
            #     continue
            # Skip processed only in normal mode
            if not (custom_start or custom_end):
                if msg_hash in processed_ids:
                    continue

            email_date = msg_header.get("Date")

            if email_date:
                email_dt = parsedate_to_datetime(email_date)

                if email_dt.tzinfo is None:
                    email_dt = email_dt.replace(tzinfo=timezone.utc)

                # Custom window filtering
                if custom_start or custom_end:

                    # Convert email time to local naive time
                    email_local = email_dt.astimezone().replace(tzinfo=None)

                    if custom_start and email_local < custom_start:
                        continue

                    if custom_end and email_local > custom_end:
                        continue

                else:
                    # Normal mode
                    if last_run and email_dt <= last_run:
                        continue

            # Fetch full message
            _, msg_data = self.mail.fetch(eid, "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])

            processed_count += 1

            email_dir = os.path.join(BASE_DIR, f"email_{processed_count}")
            attach_dir = os.path.join(email_dir, "attachments")

            os.makedirs(attach_dir, exist_ok=True)

            attachments = []

            for part in msg.walk():

                if "attachment" in str(part.get("Content-Disposition", "")).lower():

                    filename = decode_value(part.get_filename())
                    if not filename:
                        continue

                    payload = part.get_payload(decode=True)

                    filepath = os.path.join(attach_dir, filename)

                    with open(filepath, "wb") as f:
                        f.write(payload)

                    attachments.append(filepath)

            # recipients parsing
            to_field = msg.get("To", "")
            parsed_to = getaddresses([to_field])
            recipients = [email.lower() for name, email in parsed_to if email]

            # CC parsing (NEW)
            cc_field = msg.get("Cc", "")
            parsed_cc = getaddresses([cc_field])
            cc_list = [email.lower() for name, email in parsed_cc if email]

            results.append({
                "message_id": message_id,
                "message_hash": msg_hash,
                "subject": decode_value(msg.get("Subject")),
                "date": msg.get("Date"),
                "recipients": recipients,
                "cc":cc_list,
                "attachments": attachments,
                "folder_path": email_dir
            })

            if not (custom_start or custom_end):
                append_processed_id(msg_hash)

        if not (custom_start or custom_end):
            now = datetime.now(timezone.utc)
            save_last_run(now)

        print(f"{len(results)} new emails fetched")

        return results

    def close(self):
        if self.mail:
            self.mail.logout()