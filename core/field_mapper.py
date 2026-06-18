from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime


class FieldMapper:

    CONSULTANT_EMAIL_MAP = {
    "jigar.patel@acmemigration.com": "Jigarkumar Patel",
    "jagjeet@acmemigration.com": "Jagjeet Singh",
    "charu.jindal@acmemigration.com": "Deep Patel",
    "robin@acmemigration.com": "Robin Chohan",
    "adminv@acmemigration.com": "ACME Admin Vadodara",
    "ravinder@acmemigration.com": "Ravinder Matharu",
    "saaz.admin@acmemigration.com": "Saaz Admin",
    "krishna@acmemigration.com": "Krishna Saral",
    "kiratpal.singh@acmemigration.com": "Kiratpal Singh",
    "mayur.patel@acmemigration.com": "Mayur Patel",
    "zameena@acmemigration.com": "Zameena Fervin",
    "menuka.thakur@acmemigration.com": "Menuka Thakur",
    "ravi@acmemigration.com": "Ravi Shah",
    "prabhjot.rana@acmemigration.com": "Prabhjot Rana",
    "prabhjot.kaur@acmemigration.com": "Prabhjot Kaur",
    "harsh.ahm@acmemigration.com":"Harsh Karangiya",
    "rakshit.gupta229@gmail.com": "Rakshit Consultant",
    "prxxt.gurii@gmail.com": "Gurpreet Consultant",
}
    
    def _detect_consultant_from_cc(self, email_meta):

        cc_list = email_meta.get("cc", []) or []
        # print("Email Meta: ", email_meta)
        print("========")
        print("Testing email data")
        print(email_meta)
        print("========")

        found = []
        
        for email in cc_list:

            email = email.lower().strip()

            if email in self.CONSULTANT_EMAIL_MAP:
                found.append(self.CONSULTANT_EMAIL_MAP[email])

        if not found:
            return ""

        # Remove duplicates
        found = list(dict.fromkeys(found))

        ravi = "Ravi Shah"
        robin = "Robin Chohan"

        # Only Ravi / Robin present
        if set(found).issubset({ravi, robin}):
            return "\n".join(found)

        # More people present → remove Ravi/Robin
        filtered = [c for c in found if c not in {ravi, robin}]

        if filtered:
            return "\n".join(filtered)

        return "\n".join(found)

    def _detect_sponsorship_type(self, subject: str):

        if not subject:
            return "Sponsorship"

        text = subject.lower()

        if "standard business sponsorship" in text:
            return "Standard Business Sponsorship"

        if "temporary activities sponsorship" in text:
            return "Temporary Activities Sponsorship"

        return "Sponsorship"
    

    def _resolve_visa_type(self, doc, subject):

        visa = doc.get("visa_program")

        if visa == "Sponsorship":
            return self._detect_sponsorship_type(subject)

        return visa


    def _calculate_last_date(self, request_date_raw, days_to_respond):

        if not request_date_raw:
            return ""

        try:
            request_dt = datetime.strptime(request_date_raw, "%d %B %Y")

            days = int(days_to_respond or 0)

            final_days = max(days - 2, 0)

            last_dt = request_dt + timedelta(days=final_days)

            return last_dt.strftime("%d-%m-%Y")

        except:
            return ""


    def _combine_requirements(self, checklist_doc):

        if not checklist_doc:
            return ""

        applicants = checklist_doc.get("applicants", [])

        lines = []

        for app in applicants:

            reqs = app.get("requirements", [])

            for r in reqs:
                if r:
                    lines.append(r.strip())

        # remove duplicates but keep order
        seen = set()
        unique = []

        for l in lines:
            if l not in seen:
                unique.append(l)
                seen.add(l)

        return "\n".join(unique)

    # Date Formatter

    def _format_email_date(self, raw_date):

        if not raw_date:
            return ""

        try:
            dt = parsedate_to_datetime(raw_date)
            return dt.strftime("%d-%m-%Y")
        except:
            return raw_date

    def _format_doc_date(self, raw_date):

        if not raw_date:
            return ""

        try:
            dt = datetime.strptime(raw_date, "%d %B %Y")
            return dt.strftime("%d-%m-%Y")
        except:
            return raw_date
        

    # Handling Primary Secondary Applciants

    def _build_name_block(self, primary_name, secondary_names, agentcis_name):

        primary_name = (primary_name or "").strip()
        agentcis_name = (agentcis_name or "").strip()

        lines = []

        # Primary first
        if primary_name:
            lines.append(primary_name)

        # print("==========Secondary Name inside Build Name Block==========")
        # print(secondary_names)

        # Secondary applicants each on new line
        for name in secondary_names:
            if name:
                lines.append(name.strip())
                # print("secondary name: ",name )

        # Agentcis name last in brackets
        if agentcis_name:
            lines.append(f"({agentcis_name})")

        return "\n".join(lines)

    # Name Merge

    def _merge_names(self, doc_name, agentcis_name):

        doc_name = (doc_name or "").strip()
        agentcis_name = (agentcis_name or "").strip()

        if not doc_name:
            return agentcis_name

        if not agentcis_name:
            return doc_name

        if doc_name.lower() == agentcis_name.lower():
            return doc_name

        return f"{doc_name}\n({agentcis_name})"

    # Workflow

    def _workflow_status(self, doc_type, agentcis):

        status = (agentcis.get("applicationStatus") or "").lower()
        stage = (agentcis.get("currentStage") or "").lower()

        if doc_type == "acknowledgement":

            if status == "in progress" and (
                "lodgement" in stage or "outcome" in stage
            ):
                return "Yes"

            return "No"

        if doc_type == "grant":

            if status == "completed":
                return "Yes"

            return "No"

        return "No"

    # Main

    def map_to_sheet(self, payload, agentcis_data, email_meta):

        doc = payload["document"]
        doc_type = payload["document_type"]

        handled_date = self._format_email_date(email_meta.get("date"))
        subject = email_meta.get("subject", "")
        
        # S56

        if doc_type == "s56":

            checklist_doc = payload.get("checklist") or {}

            primary = doc.get("primary_applicant", {}) or {}
            secondary = doc.get("secondary_applicants", []) or {}

            primary_name = primary.get("name") or ""
            agentcis_name = agentcis_data.get("clientName") or ""

            secondary_names = [
                s.get("name") for s in secondary if s.get("name")
            ]

            final_name = self._build_name_block(
                primary_name,
                secondary_names,
                agentcis_name
            )

            request_date_raw = doc.get("date")

            request_date = self._format_doc_date(request_date_raw)

            last_date = self._calculate_last_date(
                request_date_raw,
                doc.get("days_to_respond")
            )

            info_request = self._combine_requirements(checklist_doc)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")
            sheet_fields = {

                "Email Received":
                    request_date,

                "Request Date":
                    request_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId"),

                "Consultant":
                    consultant_name,

                "Visa Type":
                    self._resolve_visa_type(doc, subject),

                "Transaction Reference\nNumber":
                    doc.get("transaction_reference_number"),

                "Email Handled Date":
                    handled_date,

                "Last Date for Submission":
                    last_date,

                "Information Request":
                    info_request,

                "Handled?":
                    "",

                "Reminder Required":
                    "",

                "Comments/ Notes":
                    ""
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }



        # BRIDGING
        
        if doc_type == "bridging_visa":
            primary_name = doc.get("name") or ""
            agentcis_name = agentcis_data.get("clientName") or ""

            secondary = doc.get("secondary_applicants", []) or []

            secondary_names = [
                s.get("name") for s in secondary if s.get("name")
            ]

            final_name = self._build_name_block(
                primary_name,
                secondary_names,
                agentcis_name
            )
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Email Received":
                    self._format_email_date(email_meta.get("date")),

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId"),

                "Consultant":
                    consultant_name,

                "Visa Type":
                    doc.get("main_visa_being_processed"),

                "Transaction Reference\nNumber":
                    doc.get("transaction_reference_number"),

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId"),

                "Bridging Visa":
                    doc.get("bridging_visa_type"),

                "Email Handled Date":
                    handled_date
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        # ==============================
        # GRANT
        # ==============================

        if doc_type == 'grant' or doc_type == 'nomination' or doc_type == 'sponsorship':
            primary = doc.get("primary_applicant", {}) or {}
            secondary = doc.get("secondary_applicants", []) or []
            # print("====Secondary Appilcant Main block====: ", secondary)

            if isinstance(primary, dict):
                primary_name = primary.get("name") or ""
            else:
                primary_name = primary or ""
            
            agentcis_name = agentcis_data.get("clientName") or ""
            

            secondary_names = [
                    s.get("name") for s in secondary if s.get("name")
                ]

            final_name = self._build_name_block(
                primary_name,
                secondary_names,
                agentcis_name
            )
            # print("====Final Name====: ", final_name)
            checklist = agentcis_data.get("checklist", {})

            form956 = checklist.get("Form 956", "NO")
            client_agreement = checklist.get("Client Agreement", "NO")
            proof_payment = checklist.get(
                "Proof of Invoice Payment (Paid/Partially Paid)",
                "NO"
            )

            workflow = self._workflow_status(doc_type, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")
            sheet_fields = {

                "Email Received":
                    self._format_email_date(email_meta.get("date")),

                "Outcome Date":
                    self._format_doc_date(doc.get("date")),

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId"),

                "Consultant":
                    consultant_name,

                "Visa Type":
                    self._resolve_visa_type(doc, subject),

                "Transaction Reference\nNumber":
                    doc.get("transaction_reference_number"),

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId"),

                "Outcome":
                    "Yes",
                    
                "Workflow Updated on Agentcis":
                    workflow,

                "Email Handled Date":
                    handled_date,

                "Comments/ Notes":
                    ""
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

# Lodgement
        primary = doc.get("primary_applicant", {}) or {}
        secondary = doc.get("secondary_applicants", []) or []
        # print("====Secondary Appilcant Main block====: ", secondary)
        primary_name = primary.get("name") or ""
        agentcis_name = agentcis_data.get("clientName") or ""

        secondary_names = [
            s.get("name") for s in secondary if s.get("name")
        ]

        final_name = self._build_name_block(
            primary_name,
            secondary_names,
            agentcis_name
        )
        # print("====Final Name====: ", final_name)
        checklist = agentcis_data.get("checklist", {})

        form956 = checklist.get("Form 956", "NO")
        client_agreement = checklist.get("Client Agreement", "NO")
        proof_payment = checklist.get(
            "Proof of Invoice Payment (Paid/Partially Paid)",
            "NO"
        )

        workflow = self._workflow_status(doc_type, agentcis_data)
        consultant_name = self._detect_consultant_from_cc(email_meta)
        if not consultant_name:
            consultant_name = agentcis_data.get("assignee")
            
        sheet_fields = {

            "Email Received":
                self._format_email_date(email_meta.get("date")),

            "Lodgement Date":
                self._format_doc_date(doc.get("date")),

            "Client Name \n(Agentcis Client Name)":
                final_name,

            "Client ID":
                agentcis_data.get("internalId"),

            "Consultant":
                consultant_name,

            "Visa Type":
                self._resolve_visa_type(doc, subject),

            "Transaction Reference\nNumber":
                doc.get("transaction_reference_number"),

            "Agentcis Application\nID":
                agentcis_data.get("applicationId"),

            "Form 956":
                form956,

            "Client Agreement":
                client_agreement,

            "Proof of Payment":
                proof_payment,

            "Workflow Updated on Agentcis":
                workflow,

            "Email Handled Date":
                handled_date,

            "Comments/ Notes":
                ""
        }

        return {
            "document_type": doc_type,
            "fields": sheet_fields
        }
