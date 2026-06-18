import re


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

        # Primary applicant (multiline DOB safe)
        primary = re.search(
            r"Primary applicant\s+(.+?)\s+\((\d{1,2}\s+\w+\s+\d{4})\)",
            self.text.replace("\n", " "),
        )

        # Secondary applicants
        secondary_block = re.search(
            r"Secondary applicants\s+(.+)",
            self.text.replace("\n", " "),
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
        
        if doc_type == "nomination_acknowledgement":
            return self.extract_nomination_acknowledgement()
        
        if doc_type == "sponsorship_acknowledgement":
            return self.extract_sponsorship_acknowledgement()

        return {"document_type": "unknown"}