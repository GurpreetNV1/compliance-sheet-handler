import re
from datetime import datetime


class IMMIExtractor:
    def __init__(self, text: str):
        self.text = text

    # Utility

    def _section(self, start_keyword, end_keyword=None):
        if end_keyword:
            pattern = rf"{start_keyword}(.*?){end_keyword}"
        else:
            pattern = rf"{start_keyword}(.*)"
        match = re.search(pattern, self.text, re.DOTALL | re.IGNORECASE)
        return match.group(1) if match else None

    def _clean(self, value):
        if not value:
            return None
        return re.sub(r"\s+", " ", value).strip()

    # Universal Visa Pattern (multiline + multiple subclass support)
    VISA_PATTERN = r"Visa\s+(.+?\(subclass\s*\d+\)(?:\s*/\s*.+?\(subclass\s*\d+\))*)"

    # DOCUMENT TYPE DETECTION

    def detect_document_type(self):

        if "Acknowledgement of sponsorship application received" in self.text:
            return "sponsorship_acknowledgement"

        if "Acknowledgement of nomination application received" in self.text:
            return "nomination_acknowledgement"

        if "Application summary" in self.text and "Providing documents" in self.text:
            return "acknowledgement"

        if "Notification of approval of a nomination" in self.text:
            return "nomination"
        
        if "Approval of a Nominated Position" in self.text:
            return "nomination_ens"

        if "Notification of approval as a" in self.text:
            return "sponsorship"

        if "Visa summary" in self.text and "Visa duration and travel" in self.text:
            return "grant"

        if "REQUEST CHECKLIST" in self.text:
            return "checklist"

        if "Request for more information for a" in self.text:
            return "s56"

        if "Bridging visa summary" in self.text:
            return "bridging_visa"

        if "Notification of refusal of application" in self.text:
            return "refusal"

        if "Notification of refusal of a nomination application" in self.text:
            return "nomination_refusal"

        # Catch-all for any other refusal variant (e.g. sponsorship) that
        # doesn't match either specific wording above — both confirmed real
        # samples start their heading with exactly "Notification of refusal
        # of", so this writes a Refusal row via the same generic
        # extract_refusal() (fields it can't find just come back blank)
        # rather than silently dropping the document as "unknown" until a
        # real sample of that shape turns up.
        if "Notification of refusal of" in self.text:
            return "refusal"

        if "Referral letter" in self.text and "Client visa details" in self.text:
            return "health_examination"

        if "Invitation to comment on information for a" in self.text:
            return "s57"

        if "Request for 2nd VAC" in self.text or "instalment of the Visa Application Charge" in self.text:
            return "s64"

        if "Appointment for Australian citizenship" in self.text:
            return "citizenship_appointment"

        if "Notice of refund" in self.text:
            return "notification"

        if "Acknowledgement of withdrawal of a nomination application" in self.text:
            return "nomination_withdrawal"

        if "Acknowledgement of withdrawal of" in self.text:
            return "withdrawal"

        if "This letter confirms that your application is progressing" in self.text:
            return "notification"

        if "Evidence of Australian citizenship" in self.text and (
            "was approved on" in self.text or "Approved" in self.text
        ):
            return "notification"

        if "Notification of approval of Australian citizenship" in self.text:
            return "notification"

        # ART (Administrative Review Tribunal) — separate case-ID scheme
        # (Online Reference Number at lodgement, numeric Case # ~1-2 weeks
        # later) from the same visa@/study@ mailboxes.

        if "REVIEW APPLICATION RECEIPT" in self.text:
            return "art_lodgement_stage1"

        if "ACKNOWLEDGEMENT OF APPLICATION" in self.text:
            return "art_lodgement_stage2"

        if "Tribunal Number:" in self.text and "Decision:" in self.text:
            return "art_outcome"

        if "Withdrawal of application for review" in self.text and "Tribunal file number" in self.text:
            return "art_outcome"

        if "NOTICE OF HEARING" in self.text:
            return "art_notice_of_hearing"

        if "REQUEST FOR INFORMATION" in self.text and "authorised recipient" in self.text:
            return "art_notification"

        # "Documents received" confirmation — system email, no PDF attachment
        # at all (body text only). A fresh online reference number is issued
        # per submission, not fixed per case, so this is a real event each
        # time, not a duplicate of an earlier one for the same case #.
        if "The ART has received the documents you sent us" in self.text:
            return "art_notification"

        return "unknown"

    # ACKNOWLEDGEMENT

    def extract_acknowledgement(self):
        section = self._section("Application summary", "Providing documents")
        if not section:
            return None

        # Primary
        primary = re.search(
            r"Primary applicant\s+(.+?)\s+\((\d{1,2}\s+\w+\s+\d{4})\)",
            section,
            re.DOTALL,
        )

        # Secondary applicants (multiline safe)
        secondary_block = re.search(
            r"Secondary applicants\s+(.+?)(?=\nVisa|\nDate of application|\nApplication ID)",
            section,
            re.DOTALL,
        )

        secondary_applicants = []

        if secondary_block:
            matches = re.findall(
                r"(.+?)\s+\((\d{1,2}\s+\w+\s+\d{4})\)",
                secondary_block.group(1),
                re.DOTALL,
            )
            for name, dob in matches:
                secondary_applicants.append({
                    "name": self._clean(name),
                    "dob": self._clean(dob),
                })

        visa_match = re.search(
            self.VISA_PATTERN,
            section,
            re.DOTALL | re.IGNORECASE,
        )

        date = re.search(
            r"Date of application\s+(\d{1,2}\s+\w+\s+\d{4})",
            section,
        )

        trn = re.search(
            r"Transaction reference number\s+([A-Z0-9]+)",
            section,
        )

        return {
            "document_type": "acknowledgement",
            "primary_applicant": {
                "name": self._clean(primary.group(1)) if primary else None,
                "dob": self._clean(primary.group(2)) if primary else None,
            },
            "secondary_applicants": secondary_applicants,
            "visa_program": self._clean(visa_match.group(1)) if visa_match else None,
            "date": date.group(1) if date else None,
            "transaction_reference_number": trn.group(1) if trn else None,
        }


    def extract_sponsorship_acknowledgement(self):

        date = re.search(r"^(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)

        applicant = re.search(
            r"Name of applicant\s+(.+)",
            self.text,
        )

        trn = re.search(
            r"Sponsorship transaction reference number\s+([A-Z0-9]+)",
            self.text,
        )

        return {
            "document_type": "acknowledgement",
            "date": date.group(1) if date else None,
            "primary_applicant": {
                "name": self._clean(applicant.group(1)) if applicant else None,
                "dob": None,
            },
            "secondary_applicants": [],
            # ============================== 
            # This sponsorship will be passed from email (IMAP)
            # ==============================
            "visa_program": "Sponsorship",
            "transaction_reference_number": trn.group(1) if trn else None,
        }
        

    def extract_nomination_acknowledgement(self):

        date = re.search(r"^(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)

        applicant = re.search(
            r"Name of applicant\s+(.+)",
            self.text,
        )

        nominee = re.search(
            r"Name of nominee\s+(.+)",
            self.text,
        )

        trn = re.search(
            r"Nomination transaction reference number\s+([A-Z0-9]+)",
            self.text,
        )

        visa = re.search(
            r"Visa program\s+(.+)",
            self.text,
        )

        secondary_applicants = []

        if applicant:
            secondary_applicants.append({
                "name": self._clean(applicant.group(1)),
                "dob": None,
            })

        visa_program = self._clean(visa.group(1)) if visa else None

        if visa_program:
            visa_program = f"{visa_program} - Nomination"

        return {
            "document_type": "acknowledgement",
            "date": date.group(1) if date else None,
            "primary_applicant": {
                "name": self._clean(nominee.group(1)) if nominee else None,
                "dob": None,
            },
            "secondary_applicants": secondary_applicants,
            "visa_program": visa_program,
            "transaction_reference_number": trn.group(1) if trn else None,
        }

    # NOMINATION

    def extract_nomination(self):
        section = self._section("In reply quote:", "Dear Sponsor")
        if not section:
            return None

        date = re.search(r"^(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)

        applicant = re.search(
            r"Name of applicant\s+(.+?)(?=\nApplication ID|\nName of nominee|\nNomination transaction reference number|\nVisa program)",
            section,
            re.DOTALL,
        )

        nominee = re.search(
            r"Name of nominee\s+(.+?)(?=\nNomination transaction reference number|\nVisa program|\nFile number)",
            section,
            re.DOTALL,
        )

        trn = re.search(
            r"Nomination transaction reference number\s+([A-Z0-9]+)",
            section,
        )

        visa = re.search(r"Visa program\s+(.+)", section)

        secondary_applicants = []

        if applicant:
            secondary_applicants.append({
                "name": self._clean(applicant.group(1)),
                "dob": None,
            })

        visa_program = self._clean(visa.group(1)) if visa else None

        if visa_program:
            visa_program = f"{visa_program} - Nomination"

        return {
            "document_type": "nomination",
            "date": date.group(1) if date else None,
            "primary_applicant": {
                "name": self._clean(nominee.group(1)) if nominee else None,
                "dob": None,
            },
            "secondary_applicants": secondary_applicants,
            "visa_program": visa_program,
            "transaction_reference_number": trn.group(1) if trn else None,
        }

    # Ens nomination
    def extract_ens_nomination(self):

    # safer section — no fragile end keyword
        section = self._section("In reply quote:")
        if not section:
            return None

        date = re.search(r"^(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)

        applicant = re.search(
            r"Name of applicant\s+(.+?)(?=\nApplication ID|\nName of nominee|\nNomination transaction reference number|\nVisa program)",
            section,
            re.DOTALL | re.IGNORECASE,
        )

        nominee = re.search(
            r"Name of nominee\s+(.+?)(?=\nNomination transaction reference number|\nVisa program|\nFile number)",
            section,
            re.DOTALL | re.IGNORECASE,
        )

        trn = re.search(
            r"Nomination transaction reference number\s+([A-Z0-9]+)",
            section,
            re.IGNORECASE,
        )

        visa = re.search(
            r"Visa program\s+(.+)",
            section,
            re.IGNORECASE,
        )

        secondary_applicants = []

        if applicant:
            secondary_applicants.append({
                "name": self._clean(applicant.group(1)),
                "dob": None,
            })

        visa_program = self._clean(visa.group(1)) if visa else None

        if visa_program:
            visa_program = f"{visa_program} - Nomination"

        return {
            "document_type": "nomination",
            "date": date.group(1) if date else None,
            "primary_applicant": {
                "name": self._clean(nominee.group(1)) if nominee else None,
                "dob": None,
            },
            "secondary_applicants": secondary_applicants,
            "visa_program": visa_program,
            "transaction_reference_number": trn.group(1) if trn else None,
        }

    # SPONSORSHIP

    def extract_sponsorship(self):
        section = self._section("In reply quote:", "Dear Sponsor")
        if not section:
            return None

        date = re.search(r"^(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)
        applicant = re.search(r"Name of applicant\s+(.+)", section)
        trn = re.search(
            r"Sponsorship transaction reference number\s+([A-Z0-9]+)",
            section,
        )

        sponsor_type = re.search(
            r"Notification of approval as a\s+(.+)",
            self.text,
        )
        
        return {
            "document_type": "sponsorship",
            "date": date.group(1) if date else None,
            "primary_applicant": {
                "name": self._clean(applicant.group(1)) if applicant else None,
                "dob": None,
            },
            "secondary_applicants": [],
            "transaction_reference_number": trn.group(1) if trn else None,
            "visa_program": self._clean(sponsor_type.group(1)) if sponsor_type else None,
        }

    # GRANT

    def extract_grant(self):
        section = self._section("Visa summary", "----- Page")
        if not section:
            section = self._section("Visa summary")

        visa_match = re.search(
            self.VISA_PATTERN,
            section,
            re.DOTALL | re.IGNORECASE,
        )

        name = re.search(r"Name\s+(.+)", section)
        dob = re.search(r"Date of birth\s+(\d{1,2}\s+\w+\s+\d{4})", section)
        date = re.search(r"Date of grant\s+(\d{1,2}\s+\w+\s+\d{4})", section)
        trn = re.search(
            r"Transaction reference number\s+([A-Z0-9]+)",
            self.text,
        )

        return {
        "document_type": "grant",
        "primary_applicant": {
            "name": self._clean(name.group(1)) if name else None,
            "dob": dob.group(1) if dob else None,
        },
        "secondary_applicants": [],
        "visa_program": self._clean(visa_match.group(1)) if visa_match else None,
        "date": date.group(1) if date else None,
        "transaction_reference_number": trn.group(1) if trn else None,
    }


    # Refusal

    def extract_refusal(self):

    # Extract refusal date (top of document)
        date_match = re.search(
            r"(\d{1,2}\s+\w+\s+\d{4})",
            self.text
        )

        # Section with structured data
        section = self._section("Application details", "The applicant's claims")

        visa = None
        name = None
        dob = None
        trn = None

        if section:
            visa_match = re.search(
                r"Visa class\s+(.+?\(subclass\s*\d+\))",
                section,
                re.DOTALL | re.IGNORECASE,
            )

            name_match = re.search(r"Client name\s+(.+)", section)
            dob_match = re.search(
                r"Date of birth\s+(\d{1,2}\s+\w+\s+\d{4})",
                section,
            )
            trn_match = re.search(
                r"Transaction reference number\s+([A-Z0-9]+)",
                section,
            )

            visa = self._clean(visa_match.group(1)) if visa_match else None
            name = self._clean(name_match.group(1)) if name_match else None
            dob = dob_match.group(1) if dob_match else None
            trn = trn_match.group(1) if trn_match else None

        # The covering letter's own "In reply quote" block states the TRN
        # too, before the attached decision record - fall back to searching
        # the whole document if the decision-record section wasn't found or
        # didn't have it. TRN now also drives the Agentcis Lodgement lookup
        # for refusals (orchestrator.py), so it's worth not depending on the
        # decision record's exact layout for this one field.
        if not trn:
            trn_fallback = re.search(
                r"Transaction reference number\s+([A-Z0-9]+)",
                self.text,
            )
            trn = trn_fallback.group(1) if trn_fallback else None

        return {
            "document_type": "refusal",
            "primary_applicant": {
                "name": name,
                "dob": dob,
            },
            "secondary_applicants": [],
            "visa_program": visa,
            "date": date_match.group(1) if date_match else None,
            "transaction_reference_number": trn,
        }


    # Nomination Refusal — different letter/decision-record layout than a
    # normal visa refusal (no "Application details"/"The applicant's claims"
    # section), so it gets its own extractor rather than reusing extract_refusal.

    def extract_nomination_refusal(self):

        # No explicit refusal date in the cover letter — the letter's own
        # issue date (top of document) is the closest real signal, same
        # fallback extract_refusal() would use if its structured section
        # were missing.
        date_match = re.search(
            r"(\d{1,2}\s+\w+\s+\d{4})",
            self.text
        )

        nominee_match = re.search(r"Name of nominee\s+(.+)", self.text)
        trn_match = re.search(
            r"Nomination transaction reference number\s+([A-Z0-9]+)",
            self.text,
        )

        # The Notice of Decision heading names the program in all caps, e.g.
        # "TRAINING(NOMINATION) SUBCLASS 407 VISA" — reconstruct it into the
        # same "<Program> (subclass N)" shape the Visa Type normalizer
        # expects, then flag it as a nomination so the normalizer picks the
        # "- Nomination" dropdown variant instead of the plain one.
        heading_match = re.search(
            r"([A-Z][A-Z ]+?)\(NOMINATION\)\s*SUBCLASS\s*(\d+)\s*VISA",
            self.text,
        )

        visa_program = None
        if heading_match:
            program_name = heading_match.group(1).strip().title()
            visa_program = f"{program_name} (subclass {heading_match.group(2)}) - Nomination"

        return {
            "document_type": "nomination_refusal",
            "primary_applicant": {
                "name": self._clean(nominee_match.group(1)) if nominee_match else None,
                "dob": None,
            },
            "secondary_applicants": [],
            "visa_program": visa_program,
            "date": date_match.group(1) if date_match else None,
            "transaction_reference_number": trn_match.group(1) if trn_match else None,
        }


    # Withdrawal — normal application (not a nomination). The letter states
    # the actual withdrawal date explicitly, unlike refusal/nomination-refusal.

    def extract_withdrawal(self):

        name_match = re.search(r"Client name\s+(.+)", self.text)
        dob_match = re.search(
            r"Date of birth\s+(\d{1,2}\s+\w+\s+\d{4})",
            self.text,
        )
        trn_match = re.search(
            r"Transaction reference number\s+([A-Z0-9]+)",
            self.text,
        )
        date_match = re.search(
            r"was withdrawn on\s*(\d{1,2}\s+\w+\s+\d{4})",
            self.text,
        )
        visa_match = re.search(
            r"Your application for a\s+(.+?)\s+visa was withdrawn",
            self.text,
            re.IGNORECASE,
        )

        return {
            "document_type": "withdrawal",
            "primary_applicant": {
                "name": self._clean(name_match.group(1)) if name_match else None,
                "dob": dob_match.group(1) if dob_match else None,
            },
            "secondary_applicants": [],
            "visa_program": self._clean(visa_match.group(1)) if visa_match else None,
            # The withdrawal date can wrap across a line break in the
            # source PDF (e.g. "27 July\n2026") — clean it the same way
            # every other multi-word field in this file already is.
            "date": self._clean(date_match.group(1)) if date_match else None,
            "transaction_reference_number": trn_match.group(1) if trn_match else None,
        }


    # Nomination Withdrawal — no explicit withdrawal date in the letter body
    # ("withdrawn as requested"), so the letter's own issue date is used
    # instead, same fallback pattern as extract_nomination_refusal.

    def extract_nomination_withdrawal(self):

        date_match = re.search(
            r"(\d{1,2}\s+\w+\s+\d{4})",
            self.text
        )

        nominee_match = re.search(r"Name of nominee\s+(.+)", self.text)
        trn_match = re.search(
            r"Nomination transaction reference number\s+([A-Z0-9]+)",
            self.text,
        )
        visa_match = re.search(r"Visa program\s+(.+)", self.text)

        visa_program = self._clean(visa_match.group(1)) if visa_match else None
        if visa_program:
            visa_program = f"{visa_program} - Nomination"

        return {
            "document_type": "nomination_withdrawal",
            "primary_applicant": {
                "name": self._clean(nominee_match.group(1)) if nominee_match else None,
                "dob": None,
            },
            "secondary_applicants": [],
            "visa_program": visa_program,
            "date": date_match.group(1) if date_match else None,
            "transaction_reference_number": trn_match.group(1) if trn_match else None,
        }


    #  REQUEST CHECKLIST


    def extract_checklist(self):
        blocks = re.split(
            r"This request checklist is for\s+",
            self.text,
        )

        applicants = []

        for block in blocks[1:]:
            lines = block.splitlines()

            name = self._clean(lines[0])

            requirements = []
            capture = False

            for line in lines[1:]:
                cleaned = self._clean(line)

                if not cleaned:
                    continue

                # Start capturing after listed below
                if "listed below" in cleaned:
                    capture = True
                    continue

                # Stop conditions
                if (
                    "The information provided below" in cleaned
                    or "Request detail" in cleaned
                    or "This request checklist is for" in cleaned
                    or "----- Page" in cleaned
                ):
                    break

                if capture:
                    # Ignore metadata lines
                    if not cleaned.startswith("Date of birth") \
                    and not cleaned.startswith("Client ID") \
                    and not cleaned.startswith("Application ID"):
                        # Checklist item labels are short noun phrases (e.g.
                        # "Police clearance certificates - INDIA"); explanatory
                        # sentences about a specific item always start with
                        # "The " (e.g. "The incorrect AFP National Police
                        # Certificate has been provided..."). Once we've
                        # captured at least one item, stop before any such
                        # sentence rather than folding it into the requirement.
                        if requirements and cleaned.startswith("The "):
                            break
                        requirements.append(cleaned)

            applicants.append({
                "name": name,
                "requirements": requirements,
            })

        return {
            "document_type": "checklist",
            "applicants": applicants,
        }


    # S56
    def extract_s56(self):
        date = re.search(r"Date:\s+(\d{1,2}\s+\w+\s+\d{4})", self.text)
        trn = re.search(r"Transaction reference number\s+([A-Z0-9]+)", self.text)
        days = re.search(r"You have\s+(\d+)\s+days", self.text)

        summary_section = self._section("Application summary", "File number")

        visa = None
        if summary_section:
            visa_match = re.search(
                self.VISA_PATTERN,
                summary_section,
                re.DOTALL | re.IGNORECASE,
            )
            if visa_match:
                visa = self._clean(visa_match.group(1))

        # Strip the page-break markers/footers inserted by the PDF reader
        # (e.g. "----- Page 4 ----- - 4 -") before name/DOB matching below —
        # otherwise a name split across a page boundary picks up this
        # artifact text instead of just the applicant's name.
        flat_text = re.sub(r"-{3,}\s*Page\s+\d+\s*-{3,}\s*-\s*\d+\s*-", " ", self.text)
        flat_text = flat_text.replace("\n", " ")

        # Primary applicant (multiline DOB safe)
        primary = re.search(
            r"Primary applicant\s+(.+?)\s+\((\d{1,2}\s+\w+\s+\d{4})\)",
            flat_text,
        )

        # Secondary applicants
        secondary_block = re.search(
            r"Secondary applicants\s+(.+)",
            flat_text,
        )

        secondary_applicants = []

        if secondary_block:
            matches = re.findall(
                r"(.+?)\s+\((\d{1,2}\s+\w+\s+\d{4})\)",
                secondary_block.group(1),
            )
            for name, dob in matches:
                secondary_applicants.append({
                    "name": self._clean(name),
                    "dob": self._clean(dob),
                })

        return {
            "document_type": "s56",
            "date": date.group(1) if date else None,
            "visa_program": visa,
            "transaction_reference_number": trn.group(1) if trn else None,
            "days_to_respond": days.group(1) if days else None,
            "primary_applicant": {
                "name": self._clean(primary.group(1)) if primary else None,
                "dob": self._clean(primary.group(2)) if primary else None,
            },
            "secondary_applicants": secondary_applicants,
        }


    def extract_bridging_visa(self):

        # 1️ Main visa being processed
        main_visa_match = re.search(
            r"while your\s+(.+?)\s+application",
            self.text,
            re.DOTALL | re.IGNORECASE,
        )

        main_visa = self._clean(main_visa_match.group(1)) if main_visa_match else None

        # 2️ Extract summary section
        section = self._section("Bridging visa summary")

        visa_type = None
        name = None
        grant_date = None
        trn = None

        if section:
            visa_type_match = re.search(r"Type\s+(.+)", section)
            name_match = re.search(r"Name\s+(.+)", section)
            grant_date_match = re.search(
                r"Date of bridging visa grant\s+(\d{1,2}\s+\w+\s+\d{4})",
                section,
            )
            trn_match = re.search(
                r"Transaction reference number\s+([A-Z0-9]+)",
                section,
            )

            visa_type = self._clean(visa_type_match.group(1)) if visa_type_match else None
            name = self._clean(name_match.group(1)) if name_match else None
            grant_date = grant_date_match.group(1) if grant_date_match else None
            trn = trn_match.group(1) if trn_match else None

        return {
            "document_type": "bridging_visa",
            "main_visa_being_processed": main_visa,
            "bridging_visa_type": visa_type,
            "name": name,
            "date_of_bridging_visa_grant": grant_date,
            "transaction_reference_number": trn,
            "secondary_applicants": [],
            }


    # -------- Shared helper for the "Client name / Date of birth / Application ID /
    # -------- Transaction reference number / File number" letter format used by
    # -------- both S57 and S64.

    def _extract_letter_header_fields(self):

        top_date = re.search(r"^(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)

        name = re.search(r"(?:Client name|Applicant name)\s+(.+)", self.text)

        dob = re.search(
            r"Date of birth\s+(\d{1,2}\s+\w+\s+\d{4})",
            self.text,
        )

        application_id = re.search(r"Application ID\s+(\S+)", self.text)

        trn = re.search(
            r"Transaction reference number\s+([A-Z0-9]+)",
            self.text,
        )

        file_number = re.search(r"File number\s+(\S+)", self.text)

        days = re.search(r"within\s+(\d+)\s+(?:calendar\s+)?days", self.text, re.IGNORECASE)

        return {
            "top_date": top_date.group(1) if top_date else None,
            "name": self._clean(name.group(1)) if name else None,
            "dob": dob.group(1) if dob else None,
            "application_id": application_id.group(1) if application_id else None,
            "transaction_reference_number": trn.group(1) if trn else None,
            "file_number": file_number.group(1) if file_number else None,
            "days_to_respond": days.group(1) if days else None,
        }

    # S57 — Invitation to comment on information (Natural Justice)

    def extract_s57(self):

        header = self._extract_letter_header_fields()

        visa_match = re.search(
            r"Invitation to comment on information for a\s+(.+?\(subclass\s*\d+\))",
            self.text,
            re.DOTALL | re.IGNORECASE,
        )

        return {
            "document_type": "s57",
            "date": header["top_date"],
            "visa_program": self._clean(visa_match.group(1)) if visa_match else None,
            "transaction_reference_number": header["transaction_reference_number"],
            "days_to_respond": header["days_to_respond"],
            "file_number": header["file_number"],
            "primary_applicant": {
                "name": header["name"],
                "dob": header["dob"],
            },
            "secondary_applicants": [],
        }

    # S64 — Request for 2nd VAC

    def extract_s64(self):

        header = self._extract_letter_header_fields()

        # Scoped pattern ("your X visa application has reached..." / "for a X
        # visa application") rather than the class-level VISA_PATTERN over the
        # whole text, which is too greedy across a multi-page letter and picks
        # up intervening text.
        visa_match = re.search(
            r"(?:your|for a)\s+(.+?\(subclass\s*\d+\))\s+visa application",
            self.text,
            re.DOTALL | re.IGNORECASE,
        )

        sponsor = re.search(r"Sponsor\s+(.+)", self.text)
        client_id = re.search(r"Client ID\s+(\d+)", self.text)

        return {
            "document_type": "s64",
            "date": header["top_date"],
            "visa_program": self._clean(visa_match.group(1)) if visa_match else None,
            "transaction_reference_number": header["transaction_reference_number"],
            "days_to_respond": header["days_to_respond"],
            "file_number": header["file_number"],
            "client_id": client_id.group(1) if client_id else None,
            "sponsor": self._clean(sponsor.group(1)) if sponsor else None,
            "primary_applicant": {
                "name": header["name"],
                "dob": header["dob"],
            },
            "secondary_applicants": [],
        }

    # Health Examinations Referral Letter

    def extract_health_examination(self):

        # The referral letter is a two-column layout; when flattened to text,
        # "Family name: X Identity document presented: Y" ends up on one line,
        # so the capture must stop before the next column's label.
        family_name = re.search(
            r"Family name:\s*(.+?)\s+Identity document presented",
            self.text,
        )
        given_names = re.search(
            r"Given names:\s*(.+?)\s+Identity document number",
            self.text,
        )
        dob = re.search(r"Date of birth:\s*(\d{1,2}\s+\w+\s+\d{4})", self.text)
        trn = re.search(r"TRN:\s*([A-Z0-9]+)", self.text)
        visa = re.search(r"Visa:\s*(.+)", self.text)

        name = " ".join(
            self._clean(part) for part in
            [given_names.group(1) if given_names else None,
             family_name.group(1) if family_name else None]
            if part
        ).strip()

        return {
            "document_type": "health_examination",
            "primary_applicant": {
                "name": name or None,
                "dob": dob.group(1) if dob else None,
            },
            "secondary_applicants": [],
            "visa_program": self._clean(visa.group(1)) if visa else None,
            "transaction_reference_number": trn.group(1) if trn else None,
        }

    # Citizenship Appointment Letter

    def extract_citizenship_appointment(self):

        name = re.search(r"Client name\s+(.+)", self.text)
        dob = re.search(r"Date of birth\s+(\d{1,2}\s+\w+\s+\d{4})", self.text)
        # "Client ID" appears once as a decoy earlier in the letter ("enter
        # Client ID number located below") before the real value — require
        # digits so the decoy (captures the word "number") doesn't match.
        client_id = re.search(r"Client ID\s+(\d+)", self.text)
        file_number = re.search(r"File number\s+(\S+)", self.text)
        trn = re.search(r"Transaction reference number\s+([A-Z0-9]+)", self.text)

        appt_date = re.search(r"Date:\s*(\d{1,2}\s+\w+\s+\d{4})", self.text)
        appt_time = re.search(r"Time:\s*(\S+)", self.text)
        appt_place = re.search(r"Place:\s*(.+?)(?=\nDuration:|\nWhat we need)", self.text, re.DOTALL)

        appointment = None
        if appt_date or appt_time:
            appointment = " ".join(
                part for part in [
                    appt_date.group(1) if appt_date else None,
                    appt_time.group(1) if appt_time else None,
                ] if part
            )

        return {
            "document_type": "citizenship_appointment",
            "primary_applicant": {
                "name": self._clean(name.group(1)) if name else None,
                "dob": dob.group(1) if dob else None,
            },
            "secondary_applicants": [],
            "client_id": client_id.group(1) if client_id else None,
            "file_number": file_number.group(1) if file_number else None,
            "transaction_reference_number": trn.group(1) if trn else None,
            "appointment_date_time": appointment,
            "appointment_place": self._clean(appt_place.group(1)) if appt_place else None,
        }

    # Generic Notification bucket — refund / assessment-commence /
    # citizenship-approval / general. One flexible extractor rather than a
    # dedicated one per subtype, since the target sheet tabs (Notifications,
    # Partner Visa Notifications, Assessment Commence Notification, S128
    # Notification of Decisions) all just want: TRN + client name + freeform text.
    # This trigger list is expected to grow as new phrasing is encountered —
    # same evolving-keyword-list style as the rest of this file.
    # (Withdrawal used to be bucketed here too, but it's now its own top-level
    # doc_type — see detect_document_type — so it can land in Outcomes with a
    # proper "Withdrawn" Outcome value instead of a freeform Notifications row.)

    def _detect_notification_subtype(self):

        if "Notice of refund" in self.text:
            return "refund"

        if "This letter confirms that your application is progressing" in self.text:
            return "assessment_commence"

        if "Evidence of Australian citizenship" in self.text:
            return "citizenship_approval"

        if "Notification of approval of Australian citizenship" in self.text:
            return "citizenship_approval"

        return "general"

    def extract_notification(self):

        subtype = self._detect_notification_subtype()

        salutation = re.search(r"Dear\s+(.+)", self.text)
        name = self._clean(salutation.group(1)) if salutation else None

        trn = None
        for label in (
            "Transaction reference number",
            "Nomination transaction reference number",
            "Sponsorship transaction reference number",
        ):
            match = re.search(rf"{label}\s+([A-Z0-9]+)", self.text)
            if match:
                trn = match.group(1)
                break

        # Try the narrower, known-safe patterns first ("Visa program X", "a X
        # (subclass N) visa") before the class-level VISA_PATTERN, which is
        # too greedy across a whole multi-page letter and can sweep up
        # intervening text if applied directly to self.text.
        visa_program = None
        visa_program_match = re.search(r"Visa program\s+(.+)", self.text)
        if visa_program_match:
            visa_program = self._clean(visa_program_match.group(1))
        else:
            visa_match = re.search(
                r"\b(?:a|an)\b\s+(.+?\(subclass\s*\d+\))\s+visa\b",
                self.text,
                re.IGNORECASE,
            )
            if visa_match:
                visa_program = self._clean(visa_match.group(1))

        # Freeform body: from the salutation line onward, lightly cleaned
        # (collapse blank-line runs, keep paragraph breaks — unlike self._clean,
        # which flattens everything to one line).
        body = None
        if salutation:
            raw_body = self.text[salutation.start():]
            body = re.sub(r"\n{2,}", "\n", raw_body).strip()

        return {
            "document_type": "notification",
            "notification_subtype": subtype,
            "name": name,
            "primary_applicant": {"name": name, "dob": None},
            "secondary_applicants": [],
            "visa_program": visa_program,
            "transaction_reference_number": trn,
            "notification_text": body,
        }

    # ==============================================================
    # ART (Administrative Review Tribunal) — separate case-ID scheme from
    # the rest of this file: an Online Reference Number is assigned at
    # lodgement, and a numeric Case # only shows up ~1-2 weeks later in a
    # separate, internal-only letter. Neither document carries both IDs, so
    # transaction_reference_number is populated with whichever ID *this*
    # stage's document carries — core/routing.py + the Apps Script upsert
    # path are what actually join stage 1 and stage 2 back together.
    # ==============================================================

    # Stage 1 — "Acknowledgement of new application lodgement" system email.
    # Client-facing (sent to both the client and visa@/study@ together).
    # Everything needed lives in the TaxInvoice.pdf attachment.

    def extract_art_lodgement_stage1(self):

        online_ref = re.search(
            r"Online Lodgement Reference No\.?:?\s*([A-Z0-9]+)", self.text
        )
        name = re.search(r"Primary Review Applicant.s name:\s*(.+)", self.text)
        lodged = re.search(r"Date Lodged:\s*(\d{2}/\d{2}/\d{4})", self.text)

        date_str = None
        if lodged:
            try:
                date_str = datetime.strptime(
                    lodged.group(1), "%d/%m/%Y"
                ).strftime("%d %B %Y")
            except ValueError:
                date_str = None

        applicant_name = self._clean(name.group(1)) if name else None

        return {
            "document_type": "art_lodgement_stage1",
            "date": date_str,
            "online_reference_number": online_ref.group(1) if online_ref else None,
            "case_number": None,
            "primary_applicant": {"name": applicant_name, "dob": None},
            "secondary_applicants": [],
            "transaction_reference_number": online_ref.group(1) if online_ref else None,
        }

    # Stage 2 — "ACKNOWLEDGEMENT OF APPLICATION" letter, ~1-2 weeks later.
    # Internal-only (never sent to the client). First appearance of Case #.

    def extract_art_lodgement_stage2(self):

        case_number = re.search(r"Case number:\s*(\d+)", self.text)
        name = re.search(r"made by\s+(.+?)\s+in\s+respect", self.text, re.DOTALL)
        date = re.search(r"^\s*(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)
        visa = re.search(r"refuse to grant a\s+(.+?)\s+visa", self.text)

        return {
            "document_type": "art_lodgement_stage2",
            "date": self._clean(date.group(1)) if date else None,
            "case_number": case_number.group(1) if case_number else None,
            "visa_program": self._clean(visa.group(1)) if visa else None,
            "primary_applicant": {
                "name": self._clean(name.group(1)) if name else None,
                "dob": None,
            },
            "secondary_applicants": [],
            "transaction_reference_number": case_number.group(1) if case_number else None,
        }

    # Outcome — two entirely different real documents map to this same
    # doc_type: the "Decision and Reasons for Decision" letter (Won/Lost,
    # self-contained — case #, applicant, and decision text all in one file)
    # and the "Withdrawal of application for review" form (always Withdrawn).

    def extract_art_outcome(self):

        if "Withdrawal of application for review" in self.text:

            case_number = re.search(r"Tribunal file number\s*\*\s*(\d+)", self.text)
            name = re.search(r"Applicant.s full name\s*\*\s*(.+)", self.text)

            return {
                "document_type": "art_outcome",
                "date": None,
                "case_number": case_number.group(1) if case_number else None,
                "outcome": "Withdrawn",
                "primary_applicant": {
                    "name": self._clean(name.group(1)) if name else None,
                    "dob": None,
                },
                "secondary_applicants": [],
                "transaction_reference_number": case_number.group(1) if case_number else None,
            }

        # "Decision and Reasons for Decision" — confirmed real samples only
        # cover the favourable ("sets aside"/"remits") wording so far; the
        # "affirm" trigger for a Lost outcome is best-effort, not yet
        # verified against a real sample.
        case_number = re.search(r"Tribunal Number:\s*(\d+)", self.text)
        name = re.search(r"Applicant\(?s?\)?:\s*(.+)", self.text)
        date = re.search(r"^Date:\s*(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)

        decision_section = self._section("Decision:", "Statement made")

        outcome = None
        if decision_section:
            lowered = decision_section.lower()
            if "sets aside" in lowered or "remits" in lowered:
                outcome = "Won"
            elif "affirm" in lowered:
                outcome = "Lost"

        return {
            "document_type": "art_outcome",
            "date": self._clean(date.group(1)) if date else None,
            "case_number": case_number.group(1) if case_number else None,
            "outcome": outcome,
            "primary_applicant": {
                "name": self._clean(name.group(1)) if name else None,
                "dob": None,
            },
            "secondary_applicants": [],
            "transaction_reference_number": case_number.group(1) if case_number else None,
        }

    # Notice of Hearing — internal-only letter. Hearing date/time/place
    # weren't confirmed against a real sample within the covering letter
    # itself (they may live deeper in the attached hearing form), so
    # "Hearing Details" is left blank rather than guessed.

    def extract_art_notice_of_hearing(self):

        case_number = re.search(r"Case number:\s*(\d+)", self.text)
        name = re.search(r"made by\s+(.+?)\s+in\s+respect", self.text, re.DOTALL)
        date = re.search(r"^\s*(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)
        visa = re.search(r"refuse to grant a\s+(.+?)\s+visa", self.text)

        return {
            "document_type": "art_notice_of_hearing",
            "date": self._clean(date.group(1)) if date else None,
            "case_number": case_number.group(1) if case_number else None,
            "visa_program": self._clean(visa.group(1)) if visa else None,
            "hearing_details": None,
            "primary_applicant": {
                "name": self._clean(name.group(1)) if name else None,
                "dob": None,
            },
            "secondary_applicants": [],
            "transaction_reference_number": case_number.group(1) if case_number else None,
        }

    # Generic ART Notifications bucket — same flexible, allow-list-trigger
    # approach as extract_notification() above (e.g. "REQUEST FOR
    # INFORMATION"). Client is essentially never a direct recipient here.

    def extract_art_notification(self):

        # "Documents received" confirmation — a system email (no PDF), whose
        # labels are markdown-bold ("*Case/review number:* 2421099"). Strip
        # the asterisks first rather than working around them in every regex.
        if "The ART has received the documents you sent us" in self.text:

            text = self.text.replace("*", "")

            online_ref = re.search(r"Online reference number:\s*(\S+)", text)
            case_number = re.search(r"Case/review number:\s*(\d+)", text)
            applicant = re.search(r"Applicant:\s*(.+)", text)
            sent_date = re.search(r"Document sent:\s*(\d{1,2}\s+\w+\s+\d{4})", text)

            return {
                "document_type": "art_notification",
                "date": self._clean(sent_date.group(1)) if sent_date else None,
                "case_number": case_number.group(1) if case_number else None,
                "online_reference_number": online_ref.group(1) if online_ref else None,
                "primary_applicant": {
                    "name": self._clean(applicant.group(1)) if applicant else None,
                    "dob": None,
                },
                "secondary_applicants": [],
                "notification_text": "Acknowledgement of receipt of documents",
                "transaction_reference_number": case_number.group(1) if case_number else None,
            }

        case_number = re.search(r"Case number:\s*(\d+)", self.text)

        name = re.search(r"made by\s+(.+?)\s+in\s+respect", self.text, re.DOTALL)
        if not name:
            salutation = re.search(r"Dear\s+(.+)", self.text)
            name = salutation

        date = re.search(r"^\s*(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)

        heading = re.search(
            r"(REQUEST FOR INFORMATION[^\n]*)", self.text
        )
        body = None
        if heading:
            raw_body = self.text[heading.start():]
            body = re.sub(r"\n{2,}", "\n", raw_body).strip()

        return {
            "document_type": "art_notification",
            "date": self._clean(date.group(1)) if date else None,
            "case_number": case_number.group(1) if case_number else None,
            "primary_applicant": {
                "name": self._clean(name.group(1)) if name else None,
                "dob": None,
            },
            "secondary_applicants": [],
            "notification_text": body,
            "transaction_reference_number": case_number.group(1) if case_number else None,
        }


    # MASTER EXTRACTOR
    def extract(self):
        doc_type = self.detect_document_type()

        if doc_type == "acknowledgement":
            return self.extract_acknowledgement()

        if doc_type == "nomination":
            return self.extract_nomination()
        
        if doc_type == "nomination_ens":
            return self.extract_ens_nomination()

        if doc_type == "sponsorship":
            return self.extract_sponsorship()

        if doc_type == "grant":
            return self.extract_grant()

        if doc_type == "checklist":
            return self.extract_checklist()

        if doc_type == "s56":
            return self.extract_s56()
        
        if doc_type == "bridging_visa":
            return self.extract_bridging_visa()
        
        if doc_type == "refusal":
            return self.extract_refusal()

        if doc_type == "nomination_refusal":
            return self.extract_nomination_refusal()

        if doc_type == "withdrawal":
            return self.extract_withdrawal()

        if doc_type == "nomination_withdrawal":
            return self.extract_nomination_withdrawal()

        if doc_type == "nomination_acknowledgement":
            return self.extract_nomination_acknowledgement()
        
        if doc_type == "sponsorship_acknowledgement":
            return self.extract_sponsorship_acknowledgement()

        if doc_type == "s57":
            return self.extract_s57()

        if doc_type == "s64":
            return self.extract_s64()

        if doc_type == "health_examination":
            return self.extract_health_examination()

        if doc_type == "citizenship_appointment":
            return self.extract_citizenship_appointment()

        if doc_type == "notification":
            return self.extract_notification()

        if doc_type == "art_lodgement_stage1":
            return self.extract_art_lodgement_stage1()

        if doc_type == "art_lodgement_stage2":
            return self.extract_art_lodgement_stage2()

        if doc_type == "art_outcome":
            return self.extract_art_outcome()

        if doc_type == "art_notice_of_hearing":
            return self.extract_art_notice_of_hearing()

        if doc_type == "art_notification":
            return self.extract_art_notification()

        return {"document_type": "unknown"}