import os
import re
import shutil
from datetime import datetime
from imap_handler.gmail_client import GmailClient
from attachment_reader.processor import AttachmentProcessor
from core.business_rules import BusinessRulesEngine
from core.field_mapper import FieldMapper
from core.routing import MAILBOX_ROUTES, resolve_write_target
from sheets.sheets_client import write_to_sheet
from sheets.art_lookup import find_client_by_case_number
from sheets.skills_lookup import find_client_by_partner_application_id
from sheets.visa_lookup import find_client_by_trn
from agentcis.agentcis_handler import AgentcisSession, find_invoice_for_application


# Generic departmental/institutional inboxes (education providers, RTOs,
# etc.) show up as recipients/cc's on real Skills Assessment mail — a real
# example, enquiries@nexgen.edu.au, was found being tried against Agentcis
# as if it might be a client. It never is a client — these are addresses
# other organisations expose for general contact, not individuals.
_INSTITUTIONAL_EMAIL_PREFIXES = (
    "enquiries@", "enquiry@", "info@", "admin@", "support@", "contact@",
    "office@", "noreply@", "no-reply@", "help@", "service@",
)


def _looks_institutional(email: str) -> bool:
    email = email.lower()
    # Government/authority domains (VETASSESS, ACECQA, DEWR, ANMAC, etc. all
    # use .gov.au or similar) are never a client — real client mail always
    # comes from a personal or corporate address, not a .gov one.
    if ".gov" in email.split("@")[-1]:
        return True
    return email.startswith(_INSTITUTIONAL_EMAIL_PREFIXES)


class Orchestrator:

    def __init__(self):

        self.mailboxes = {
            mailbox: GmailClient(mailbox) for mailbox in MAILBOX_ROUTES
        }
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

        # ART (Administrative Review Tribunal) subjects are just
        # "<case#> - <name> [SEC=OFFICIAL:...]" or "Fwd:" of the same — none
        # of the IMMI keywords above appear at all. "sec=official" showed up
        # in every real ART subject checked; a bare 6-7 digit case number is
        # a fallback for the rare one that doesn't (e.g. a consultant's own
        # composed subject line referencing the case #).
        if "sec=official" in subject:
            return True

        if re.search(r"\b\d{6,7}\b", subject):
            return True

        # Skills Assessment (VETASSESS/EA/TRA) subjects are too varied to
        # share one marker like ART's "SEC=OFFICIAL" — and since these are
        # always internally-forwarded emails, the real authority's sending
        # domain lives inside the forwarded headers in the body text, not
        # the (our own mailbox's) Gmail "From" header. So this checks body
        # text too, for either the real sending domain or a distinctive
        # authority phrase.
        body = (email_meta.get("body_text") or "").lower()
        skills_markers = [
            "vetassess", "engineersaustralia", "engineers australia",
            "dewr.gov.au", "ssc.gov.au", "trades recognition australia",
            "job ready program", "provisional skills assessment",
        ]
        if any(m in subject or m in body for m in skills_markers):
            return True

        if re.search(r"\bTRA\d{2}/\d{6,10}\b", email_meta.get("subject") or "") or \
           re.search(r"\bTRA\d{2}/\d{6,10}\b", email_meta.get("body_text") or ""):
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
        # storage/ holds per-email attachment/body caches; logs/raw and
        # logs/extracted hold a timestamped file per PDF ever processed —
        # none of it persists value past the run that created it, and left
        # alone it piles up indefinitely (confirmed: 3000+ files in each
        # logs subfolder). Cleared fresh at the start of every run.
        for folder_path in ("storage", "logs/raw", "logs/extracted"):

            if not os.path.exists(folder_path):
                continue

            for item in os.listdir(folder_path):

                item_path = os.path.join(folder_path, item)

                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)

                except Exception as e:
                    print(f"Failed deleting {item_path}: {e}")

        print("Storage and logs cleaned")

    # main run 

    def run(self):

        print("\n")
        print("STARTING AUTOMATION")
        print("\n")

        self._clean_storage_startup()

        print("\nChoose mode:")
        print("1 -> Process new unprocessed emails (default)")
        print("2 -> Process custom date range")

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

        any_emails = False

        # Login to Agentcis once, shared across every mailbox
        self.agentcis.login()

        for mailbox, client in self.mailboxes.items():

            print(f"\n==== Mailbox: {mailbox} ====")

            client.connect()

            emails = client.fetch_new_emails(
                custom_start=custom_start,
                custom_end=custom_end
            )

            if not emails:
                print(f"No new emails found for {mailbox}")
                client.close()
                continue

            any_emails = True

            for email in emails:
                if not self._is_relevant_email(email):
                    print("Skipping unrelated email:", email.get("subject"))
                    continue

                try:
                    self._process_email(mailbox, email)

                except Exception as e:
                    print(f"Email processing failed: {e}")

            client.close()

        self.agentcis.close()

        if not any_emails:
            print("No new emails found across any mailbox")

        print("\nAUTOMATION COMPLETE")

    # Process every email

    def _process_email(self, mailbox: str, email_meta: dict):

        print("\n----------------------------------")
        print("Processing Email:", email_meta["subject"])
        print("----------------------------------")

        attachment_dir = os.path.join(
            email_meta["folder_path"],
            "attachments"
        )


        # Step 1 — Extract PDFs
        extracted_docs = self.processor.process_folder(
            attachment_dir,
            subject=email_meta.get("subject"),
        )

        # Some correspondence (ART's "documents received" confirmation,
        # several Skills Assessment notifications) has no PDF attachment at
        # all — everything needed is only in the email body.
        body_doc = self.processor.process_email_body(
            email_meta.get("body_text"),
            subject=email_meta.get("subject"),
        )
        if body_doc:
            extracted_docs.append(body_doc)

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

        # "unknown" never resolves to a write target (routing.py has no tab
        # mapping for it) — driving an Agentcis search off one wastes a real
        # search attempt and can search recipients that would never be
        # tried for a real doc type. Confirmed live: a "Customer Invoice"
        # email's only extracted doc was "unknown" (an unrecognized PDF),
        # yet it still drove a recipient search that tried EA's own
        # invoicing department addresses on Agentcis.
        entry_payloads = [
            p for p in entry_payloads
            if (p["document"].get("document_type") or "unknown") != "unknown"
        ]

        if not entry_payloads:
            print("No actionable documents (all unknown)")
            return

        # Step 3 — Agentcis fetch
        # Always returns a dict (possibly empty {} if no match was found via
        # recipient or name search) — never None, never skips the email.
        # field_mapper's agentcis_data.get(...) calls simply come back blank,
        # matching the "Client not found in Agentcis" pattern already seen in
        # the live sheet, rather than silently dropping the whole email.
        agentcis_data = self._fetch_agentcis_data(
            email_meta,
            entry_payloads[0]
        )

        # Step 3b — Revenue. An invoice is created the moment an
        # application is lodged, so this only fires for lodgement-type
        # entries — confirmed live that a real Lodgement's Client ID +
        # Agentcis Application ID reliably finds its matching invoice via
        # application_id. Attached onto agentcis_data (rather than passed
        # separately) so every downstream field_mapper branch already
        # receiving agentcis_data picks it up with no signature changes.
        lodgement_doc_types = {"acknowledgement", "skills_lodgement", "art_lodgement_stage1"}
        is_lodgement = any(
            (p["document"].get("document_type") or "") in lodgement_doc_types
            for p in entry_payloads
        )
        if is_lodgement and agentcis_data.get("internalId"):
            try:
                invoices = self.agentcis.fetch_invoices(agentcis_data["internalId"])
                invoice = find_invoice_for_application(invoices, agentcis_data.get("applicationId"))
                if invoice:
                    agentcis_data["revenue_invoice"] = invoice
                    print(f"Revenue matched: invoice {invoice['id']} — {invoice['invoice_amount']['formatted']}")
                else:
                    print(f"No invoice found for application {agentcis_data.get('applicationId')!r}")
            except Exception as e:
                print(f"Revenue lookup failed: {e}")

        # Step 4 — Write each entry
        for payload in entry_payloads:

            sheet_data = self.mapper.map_to_sheet(
                payload,
                agentcis_data,
                email_meta
            )

            url, tab_name = resolve_write_target(
                mailbox, sheet_data["document_type"], payload.get("document")
            )

            if not url:
                print(
                    f"No write target for document_type="
                    f"{sheet_data['document_type']!r} from {mailbox} — skipping"
                )
                continue

            match_name = sheet_data.get("match_name")

            write_to_sheet(
                url,
                tab_name,
                sheet_data["fields"],
                action="upsert_by_name" if match_name else None,
                match_name=match_name,
            )

        print("Email completed")


    # Best-effort applicant name, for the name-search fallback below.
    def _extract_applicant_name(self, doc):

        primary = doc.get("primary_applicant")
        if isinstance(primary, dict) and primary.get("name"):
            return primary["name"]

        if doc.get("name"):
            return doc["name"]

        return None

    # Agentcis logic with retries

    def _fetch_agentcis_data(self, email_meta, payload):

        recipients = email_meta.get("recipients", [])

        doc = payload["document"]

        doc_type = payload.get("document_type") or doc.get("document_type") or ""

        # Skills Assessment mail follows a materially different reliability
        # pattern from IMMI/ART documents — confirmed live and by the user
        # directly: a real client email in the recipients is only reliable
        # for TRA; every other authority is internal-only correspondence,
        # and Agentcis name search is too risky (common names return many
        # unrelated contacts). Handled by its own method rather than
        # threading more special cases through the IMMI/ART flow below.
        if doc_type.startswith("skills_"):
            return self._fetch_agentcis_data_skills(email_meta, doc)

        # Refusal and withdrawal letters are sent to visa@/study@ only,
        # never cc'ing the client — there's no client email to search
        # Agentcis with, and the applicant's name alone risks ambiguity
        # (same reasoning as Skills Assessment above). The Transaction
        # Reference Number is stable across the case's whole lifecycle, so
        # this looks up the original Lodgement row instead of guessing —
        # same pattern as _fetch_agentcis_data_skills's Partner Application
        # ID lookup.
        if doc_type in ("refusal", "nomination_refusal", "withdrawal", "nomination_withdrawal"):
            return self._fetch_agentcis_data_visa_by_trn(doc)

        visa_name = self._resolve_visa_name(doc, email_meta)



        for r in recipients:

            # Our own staff addresses (@acmemigration.com) show up in
            # recipients constantly — internal forwards, CCs, the mailbox's
            # own "To" on a reply — but they are never a client in Agentcis.
            # Trying them wastes a full search (and has been seen to hang/
            # time out the browser on a name that doesn't exist) instead of
            # failing fast, so they're skipped before ever reaching Agentcis.
            if r.endswith("@acmemigration.com"):
                continue

            if _looks_institutional(r):
                print(f"Skipping institutional-looking address: {r}")
                continue

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

        # ART-specific fallback — the numeric Case # is stable across every
        # stage of a case, so if an earlier entry for the same case already
        # exists anywhere in the ART sheet, its recorded Client Name/ID/
        # Consultant is more reliable than a fresh name search (ART
        # documents sometimes only carry a bare surname, which name search
        # can't disambiguate). Checked before the name-search fallback below.
        case_number = doc.get("case_number")
        if case_number:
            try:
                case_data = find_client_by_case_number(case_number)
                if case_data:
                    print(f"Matched via existing Case # {case_number} record: {case_data}")
                    # Already a verified full name from a previously-recorded
                    # row — not a same-name confirmation like Agentcis, so
                    # field_mapper should use it as-is rather than bracketing
                    # it behind whatever partial name this document extracted.
                    case_data["_resolved_via_case_lookup"] = True
                    return case_data
            except Exception as e:
                print(f"Case # lookup failed for {case_number}: {e}")

        # (Skills Assessment doc types never reach this point — they return
        # early via _fetch_agentcis_data_skills above, which has its own
        # Partner Application ID lookup + direct Client ID fetch.)

        # Fallback — name-based search, for document types where the client is
        # rarely (or never) a direct recipient (S57 confirmed ~100% internal
        # forwards, ART ~97%, S64/Citizenship Appointment mixed). Only
        # auto-accepted when AgentcisSession.fetch_by_name finds an unambiguous
        # single match; otherwise treated the same as no-match below.
        applicant_name = self._extract_applicant_name(doc)

        if applicant_name:
            try:
                print(f"Trying Agentcis name search with: {applicant_name}")

                data = self.agentcis.fetch_by_name(applicant_name, visa_name)

                if data:
                    print("Agentcis matched via name search")
                    return data

            except Exception as e:
                print(f"Agentcis name search failed for {applicant_name}: {e}")

        print("No Agentcis match found — will write row with blank Agentcis fields")

        return {}

    # Skills Assessment — deliberately separate from the IMMI/ART flow
    # above, per direct user feedback after reviewing a real live batch:
    # a real client email in recipients is only reliable for TRA; every
    # other authority is internal-only correspondence, and name search is
    # too risky here (common names return many unrelated Agentcis
    # contacts). So for anything except TRA, this skips recipient/name
    # search entirely and instead looks up the Client ID already recorded
    # for this case in the Lodgement tab, then fetches that client
    # directly by ID (agentcis.fetch_by_client_id) — no search, no
    # ambiguity. TRA still falls through to the same cross-reference if no
    # usable recipient email is found.
    def _fetch_agentcis_data_skills(self, email_meta, doc):

        recipients = email_meta.get("recipients", [])
        authority = doc.get("authority")
        partner_id = doc.get("partner_application_id")

        if authority == "TRA":
            # The real Payment Receipt template states the applicant's own
            # email directly in the body ("Applicant Email: ...") — the
            # recipients list on this internal forward is usually all
            # acmemigration.com staff, so this is the actual reliable
            # source, tried first. Confirmed live: a brand-new TRA case
            # (BALA SUMANTH REDDY VATTI) reported "no match" despite the
            # email stating "Applicant Email: balasumanthreddy3@gmail.com"
            # in its body, because only the recipients list was ever tried.
            search_candidates = []
            applicant_email = doc.get("applicant_email")
            if applicant_email:
                search_candidates.append(applicant_email)
            search_candidates.extend(recipients)

            for r in search_candidates:
                if r.endswith("@acmemigration.com"):
                    continue
                if _looks_institutional(r):
                    print(f"Skipping institutional-looking address: {r}")
                    continue
                try:
                    print(f"Trying Agentcis with: {r}")
                    data = self.agentcis.fetch(r, "", authority=authority)
                    if data:
                        print("Agentcis matched")
                        return data
                except Exception as e:
                    print(f"Agentcis failed for {r}: {e}")

        if partner_id:
            try:
                partner_data = find_client_by_partner_application_id(partner_id)
            except Exception as e:
                print(f"Partner Application ID lookup failed for {partner_id}: {e}")
                partner_data = None

            if partner_data and partner_data.get("internalId"):
                try:
                    print(f"Found Client ID {partner_data['internalId']} via Lodgement record — fetching directly")
                    live_data = self.agentcis.fetch_by_client_id(partner_data["internalId"], "", authority=authority)
                    if live_data:
                        print("Agentcis matched via direct Client ID lookup")
                        return live_data
                except Exception as e:
                    print(f"Direct Client ID fetch failed for {partner_data['internalId']}: {e}")

            if partner_data:
                print(f"Matched via existing Partner Application ID {partner_id} record: {partner_data}")
                # No live re-check succeeded above — this is the previously
                # recorded text, not a fresh confirmation, so field_mapper
                # should use the name as-is rather than bracketing it
                # behind whatever partial name this document extracted.
                partner_data["_resolved_via_case_lookup"] = True
                return partner_data

        print("No Agentcis match found for Skills Assessment doc — will write row with blank Agentcis fields")
        return {}

    # Refusal / Withdrawal (and their nomination variants) — no client email
    # to search (always sent to visa@/study@ only, then forwarded to the
    # handling consultant internally), so this skips recipient/name search
    # entirely, same as _fetch_agentcis_data_skills. If the original
    # Lodgement row can't be found (the lodgement may have happened years
    # earlier and no longer be in the sheet's history), this returns {} —
    # the row still gets written with whatever the letter itself provided
    # (name, TRN, visa type, date, Outcome), just with blank Agentcis fields
    # for staff to fill in by hand.
    def _fetch_agentcis_data_visa_by_trn(self, doc):

        trn = doc.get("transaction_reference_number")

        if trn:
            try:
                trn_data = find_client_by_trn(trn)
            except Exception as e:
                print(f"TRN lookup failed for {trn}: {e}")
                trn_data = None

            if trn_data and trn_data.get("internalId"):
                try:
                    print(f"Found Client ID {trn_data['internalId']} via Lodgement record — fetching directly")
                    live_data = self.agentcis.fetch_by_client_id(trn_data["internalId"], "")
                    if live_data:
                        print("Agentcis matched via direct Client ID lookup")
                        return live_data
                except Exception as e:
                    print(f"Direct Client ID fetch failed for {trn_data['internalId']}: {e}")

            if trn_data:
                print(f"Matched via existing Transaction Reference Number {trn} record: {trn_data}")
                trn_data["_resolved_via_case_lookup"] = True
                return trn_data

        print("No Lodgement record found for this Transaction Reference Number — will write row with blank Agentcis fields")
        return {}
