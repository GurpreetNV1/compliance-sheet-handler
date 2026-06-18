import os
import shutil
from datetime import datetime
from imap_handler.imap_client import ImapClient
from attachment_reader.processor import AttachmentProcessor
from core.business_rules import BusinessRulesEngine
from core.field_mapper import FieldMapper
from sheets.sheets_handler import write_to_excel
from agentcis.agentcis_handler import AgentcisSession


class Orchestrator:

    def __init__(self):

        self.imap = ImapClient()
        self.processor = AttachmentProcessor()
        self.rules = BusinessRulesEngine()
        self.mapper = FieldMapper()

        self.agentcis = AgentcisSession()


    
    def _is_relevant_email(self, email_meta):

        subject = (email_meta.get("subject") or "").lower()

        keywords = [
            "grant",
            "visa application",
            "s56",
            "nomination",
            "approval",
            "acknowledgement",
            "bridging", 
            "sponsorship",
            "application",
            "visa",
            "visa application documents",
        ]

        # Direct keyword match
        if any(k in subject for k in keywords):
            return True

        # Reply detection (Re:, Fwd:)
        if subject.startswith("re:") or subject.startswith("fw:") or subject.startswith("fwd:"):
            for k in keywords:
                if k in subject:
                    return True

        return False


    # Resloving Sponsorship
    def _resolve_visa_name(self, doc, email_meta):

        subject = email_meta.get("subject", "")

        visa = (
            doc.get("visa_program")
            or doc.get("main_visa_being_processed")
            or doc.get("sponsorship_type")
            or ""
        )

        # Sponsorship → use subject text
        if visa == "Sponsorship":
            return subject

        return visa



# Cleanup
    def _clean_storage_startup(self):
        storage_path = "storage"

        if not os.path.exists(storage_path):
            return

        # print("Cleaning storage folder before run...")

        for item in os.listdir(storage_path):

            item_path = os.path.join(storage_path, item)

            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    os.remove(item_path)

            except Exception as e:
                print(f"Failed deleting {item_path}: {e}")

        print("Storage cleaned")

    # main run 

    def run(self):

        print("\n")
        print("STARTING AUTOMATION")
        print("\n")

        self._clean_storage_startup() 
        self.imap.connect()

        # emails = self.imap.fetch_new_emails()
        print("\nChoose mode:")
        print("1 → Process new unprocessed emails (default)")
        print("2 → Process custom date range")

        choice = input("Enter choice: ").strip()

        custom_start = None
        custom_end = None

        if choice == "2":

            start_str = input("Enter start datetime (YYYY-MM-DD HH:MM): ").strip()
            end_str = input("Enter end datetime (YYYY-MM-DD HH:MM): ").strip()

            try:
                custom_start = datetime.strptime(start_str, "%Y-%m-%d %H:%M")
                custom_end = datetime.strptime(end_str, "%Y-%m-%d %H:%M")
            except Exception:
                print("Invalid datetime format")
                return

        emails = self.imap.fetch_new_emails(
            custom_start=custom_start,
            custom_end=custom_end
        )

        if not emails:
            print("No new emails found")
            return
        
        # cleanup

        # Login once
        self.agentcis.login()

    # original, Processes every email
        # for email in emails:

        #     try:
        #         self._process_email(email)

        #     except Exception as e:
        #         print(f"Email processing failed: {e}")


        # Fitlers on the basis of subject keywords 
        for email in emails:
            if not self._is_relevant_email(email):
                print("Skipping unrelated email:", email.get("subject"))
                continue

            try:
                self._process_email(email)

            except Exception as e:
                print(f"Email processing failed: {e}")


        self.imap.close()
        self.agentcis.close()

        print("\nAUTOMATION COMPLETE")

    # Process every email

    def _process_email(self, email_meta: dict):

        print("\n----------------------------------")
        print("Processing Email:", email_meta["subject"])
        print("----------------------------------")

        attachment_dir = os.path.join(
            email_meta["folder_path"],
            "attachments"
        )

        
        # Step 1 — Extract PDFs
        extracted_docs = self.processor.process_folder(
            attachment_dir
        )

        if not extracted_docs:
            print("No documents extracted")
            return

        # Step 2 — Apply Business Rules
        entry_payloads = self.rules.decide_entries(
            extracted_docs
        )

        if not entry_payloads:
            print("No entries decided")
            return

        # Step 3 — Agentcis fetch
        agentcis_data = self._fetch_agentcis_data(
            email_meta,
            entry_payloads[0]
        )

        if not agentcis_data:
            print("Agentcis data not found — skipping email")
            return

        # Step 4 — Write each entry
        for payload in entry_payloads:

            sheet_data = self.mapper.map_to_sheet(
                payload,
                agentcis_data,
                email_meta
            )

            write_to_excel(sheet_data)

        

        print("Email completed")


    # Agentcis logic with retries

    def _fetch_agentcis_data(self, email_meta, payload):

        recipients = email_meta.get("recipients", [])

        doc = payload["document"]

        visa_name = self._resolve_visa_name(doc, email_meta)

        

        for r in recipients:

            try:
                print(f"Trying Agentcis with: {r}")

                data = self.agentcis.fetch(
                    r,
                    visa_name
                )

                if data:
                    print("Agentcis matched")
                    return data

            except Exception as e:
                print(f"Agentcis failed for {r}: {e}")

        print("No Agentcis match found")

        return None
