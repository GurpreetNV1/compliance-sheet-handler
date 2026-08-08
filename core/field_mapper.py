import re
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
    "harsh.ahm@acmemigration.com": "Harsh",
    "riddhi.joshi@acmemigration.com": "Riddhi Joshi",
    "admissions2@acmemigration.com": "Helly Parikh",
    "mona.singh@acmemigration.com": "Mona Singh",
    "admissions@acmemigration.com": "Parabhdeep Singh",
    "babita@acmemigration.com": "Babita Garg",
    "studentcounsellor2@acmemigration.com": "Shihab Uddin Chowdhury",
    "studentcounsellor1@acmemigration.com": "Manpreet Kaur Virk",
    "meenal@acmemigration.com": "Meenal Patel",
    "sunaina@acmemigration.com": "Sunaina",
    "mansi@acmemigration.com": "Mansi",
    "nisha@acmemigration.com": "Nisha Sorari",
    "naman@acmemigration.com": "Naman",
}

    # Visa Outcomes tab uses "Grant"/"Refusal"/"Withdrawn" as the Outcome
    # column's vocabulary, same as staff's own manual entries — not Yes/No.
    # Nomination/sponsorship approvals are treated as "Grant" (a positive
    # outcome, consistent with them already sharing this branch).
    IMMI_OUTCOME_LABELS = {
        "grant": "Grant",
        "nomination": "Grant",
        "sponsorship": "Grant",
        "refusal": "Refusal",
        "nomination_refusal": "Refusal",
        "withdrawal": "Withdrawn",
        "nomination_withdrawal": "Withdrawn",
    }

    # Exact "Visa Type" dropdown options, read directly from the Visa and
    # Student sheets' data validation rules — not derived from wording we
    # guessed. Extracted visa_program text is close to these but often
    # differs in small ways (extra qualifier words, missing "Subsequent
    # Entrant", stream names like "(Tourist)"/"(Sponsored)" that the
    # dropdown doesn't distinguish), which is exactly why staff had to
    # reselect from the dropdown by hand after every write.
    VISA_TYPE_DROPDOWN_VALUES = (
        "Bridging B Visa",
        "Citizenship by Conferral",
        "DAMA Endorsement Application",
        "DAMA Labour Agreement",
        "DAMA Labour Agreement In Effect",
        "Employer Nomination Scheme (subclass 186)",
        "Employer Nomination Scheme (subclass 186) - Nomination",
        "Evidence of Australian Citizenship",
        "New Zealand Citizen Family Relationship (subclass 461)",
        "Parent Sponsor in relation to a Sponsored Parent (Temporary) (subclass 870) - Sponsorship",
        "Parent Sponsor in relation to a Sponsored Parent (Temporary) (subclass 870) visa",
        "Partner (Provisional) (subclass 309)",
        "Partner (subclass 100)",
        "Partner (subclass 309)/Partner (subclass 100)",
        "Partner (subclass 801)",
        "Partner (subclass 820)",
        "Partner (subclass 820)/Partner (subclass 801)",
        "Permanent Residence (Skilled Regional) (subclass 191)",
        "Resident Return (subclass 155) Visa",
        "Skilled - Independent (subclass 189)",
        "Skilled - Nominated (subclass 190)",
        "Skilled - Regional (subclass 887)",
        "Skilled Employer Sponsored Regional (Provisional) (subclass 494)",
        "Skilled Employer Sponsored Regional (Provisional) (subclass 494) - Nomination",
        "Skilled Work Regional (Provisional) (subclass 491)",
        "Skilled Work Regional (Provisional) (Subsequent Entrant) (subclass 491)",
        "Skills in Demand (subclass 482)",
        "Skills in Demand (subclass 482) - Nomination",
        "Sponsored Parent (Temporary) (subclass 870)",
        "Standard Business Sponsor",
        "Temporary Activities Sponsor",
        "Temporary Activity (Subsequent Entrant) (subclass 408)",
        "Temporary Graduate (subclass 485)",
        "Temporary Graduate (Subsequent Entrant) (subclass 485)",
        "Temporary Skill Shortage (subclass 482)",
        "Temporary Skill Shortage (subclass 482) - Nomination",
        "Temporary Work (subclass 400)",
        "Training (subclass 407)",
        "Training (subclass 407) - Nomination",
        "Visitor (subclass 600)",
        "Working Holiday (Extension) (subclass 417) visa",
        # Student sheet's own "Visa Type"-equivalent column.
        "Student (subclass 500)",
        "Student (Subsequent Entrant) (subclass 500)",
    )

    # Phrases that distinguish two dropdown options sharing the same
    # subclass number, beyond the "- Nomination" suffix (checked
    # separately). "Skills in Demand"/"Temporary Skill Shortage" are the
    # old/new names for the same subclass 482 program (renamed Dec 2024) —
    # whichever one the source document actually used is what should be
    # matched, not always the newer name.
    _VISA_TYPE_DISTINGUISHING_PHRASES = (
        "subsequent entrant",
        "skills in demand",
        "temporary skill shortage",
    )

    @staticmethod
    def _visa_type_subclass_numbers(value):
        return set(re.findall(r"subclass\s*(\d+)", value.lower()))

    @staticmethod
    def _visa_type_is_nomination(value):
        # A strict "- Nomination" suffix, not a bare substring match — the
        # base "Employer Nomination Scheme (subclass 186)" option already
        # has "Nomination" in its own name and must not be mistaken for the
        # dedicated "- Nomination" variant.
        return bool(re.search(r"-\s*nomination\s*$", value.strip(), re.IGNORECASE))

    def _normalize_visa_type_for_dropdown(self, visa_program):
        if not visa_program:
            return visa_program

        lower = visa_program.lower()
        raw_numbers = set(re.findall(r"subclass\s*(\d+)", lower))
        if not raw_numbers:
            # No subclass number to key off (e.g. "Bridging B Visa",
            # sponsorship types) — nothing to normalize against.
            return visa_program

        # A combined "X/Y" entry (e.g. Partner subclass 820/801) applies
        # only when the source text references every subclass number that
        # entry covers.
        combined_matches = [
            value for value in self.VISA_TYPE_DROPDOWN_VALUES
            if len(self._visa_type_subclass_numbers(value)) > 1
            and self._visa_type_subclass_numbers(value).issubset(raw_numbers)
        ]
        if len(combined_matches) == 1:
            return combined_matches[0]

        single_candidates = [
            value for value in self.VISA_TYPE_DROPDOWN_VALUES
            if len(self._visa_type_subclass_numbers(value)) == 1
            and self._visa_type_subclass_numbers(value).issubset(raw_numbers)
        ]
        if not single_candidates:
            return visa_program

        raw_is_nomination = self._visa_type_is_nomination(visa_program)
        nomination_filtered = [
            value for value in single_candidates
            if self._visa_type_is_nomination(value) == raw_is_nomination
        ]
        if not nomination_filtered:
            return visa_program

        if len(nomination_filtered) == 1:
            return nomination_filtered[0]

        raw_phrases = {p for p in self._VISA_TYPE_DISTINGUISHING_PHRASES if p in lower}
        scored = [
            (value, {p for p in self._VISA_TYPE_DISTINGUISHING_PHRASES if p in value.lower()})
            for value in nomination_filtered
        ]
        group_phrases = set().union(*(phrases for _, phrases in scored))
        target = raw_phrases & group_phrases

        exact = [value for value, phrases in scored if phrases == target]
        if len(exact) == 1:
            return exact[0]

        # Genuinely ambiguous (e.g. the 3 distinct subclass-870 entries,
        # which share no distinguishing signal) — leave as-is rather than
        # guess wrong; staff picks the right one from the dropdown by hand,
        # same as today.
        return visa_program

    def _detect_consultant_from_cc(self, email_meta):

        # Skills Assessment mail (VETASSESS/EA/TRA/etc.) is internally
        # forwarded rather than cc'd — the handling consultant ends up in
        # the forward's "To", not "Cc". CONSULTANT_EMAIL_MAP is a fixed
        # whitelist of known staff addresses, so checking recipients too is
        # safe for every doc type: a real client's address is never in it.
        cc_list = (email_meta.get("cc", []) or []) + (email_meta.get("recipients", []) or [])
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

        # A real ACS email was found addressed to ~13 internal staff at
        # once (a broad team distribution, not a "forwarded to the handling
        # consultant" pattern) — with recipients now checked alongside cc,
        # that produced a useless 7-name list. More than 2 distinct names
        # after the Ravi/Robin filter means this recipient list isn't a
        # reliable single-consultant signal, so it's treated as
        # inconclusive rather than dumping every name into the field.
        if len(filtered) > 5:
            return ""

        # Up to 5 real candidates remain — take whoever appears first in
        # cc/recipient order as the single handling consultant, rather than
        # writing multiple names.
        if filtered:
            return filtered[0]

        return "\n".join(found)

    def _detect_sponsorship_type(self, subject: str):

        # "Standard Business Sponsor" / "Temporary Activities Sponsor" are
        # the actual dropdown options (no "-ship" suffix) — confirmed
        # against the real Visa Type dropdown, not guessed from wording.
        if not subject:
            return "Sponsorship"

        text = subject.lower()

        if "standard business sponsorship" in text:
            return "Standard Business Sponsor"

        if "temporary activities sponsorship" in text:
            return "Temporary Activities Sponsor"

        return "Sponsorship"


    def _resolve_visa_type(self, doc, subject):

        visa = doc.get("visa_program")

        if visa == "Sponsorship":
            return self._detect_sponsorship_type(subject)

        return self._normalize_visa_type_for_dropdown(visa)


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

    # Week Range — Friday-anchored 7-day window containing "now" (write time,
    # not the document/email date — matches Dashboard/frontend/src/hooks/useDashboardData.js
    # getDefaultDateRange, which treats every reporting week as ending on a Friday).

    def _compute_week_range(self, now=None):

        now = now or datetime.now()
        days_since_friday = (now.weekday() - 4) % 7

        week_start = now - timedelta(days=days_since_friday)
        week_end = week_start + timedelta(days=7)

        return f"{week_start:%Y-%m-%d} to {week_end:%Y-%m-%d}"


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

    # ART — same "primary name + Agentcis name in brackets" convention as
    # every other single-applicant doc type, factored out since 4 of the 5
    # ART doc types need it identically.

    def _art_final_name(self, doc, agentcis_data):

        # A Case #-based lookup returns an already-verified full name from a
        # previously-recorded row (e.g. resolving a bare surname like
        # "KYADA" to "Chintan Rajeshbhai Kyada") — use it as-is rather than
        # bracketing it behind the partial name this document extracted.
        if agentcis_data.get("_resolved_via_case_lookup"):
            return agentcis_data.get("clientName") or ""

        primary = doc.get("primary_applicant", {}) or {}
        primary_name = primary.get("name") or doc.get("name") or ""
        agentcis_name = agentcis_data.get("clientName") or ""

        return self._build_name_block(primary_name, [], agentcis_name)

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

    def _normalize_checklist_value(self, value):

        if str(value).strip().lower() == "yes":
            return "Yes"

        return "No"

    # Revenue — an invoice is created the moment an application is lodged
    # (confirmed live: every real Lodgement entry tested has a matching
    # Agentcis invoice by application_id, same run). Already-AUD invoices
    # are written as a plain number; anything else is written as a
    # GOOGLEFINANCE formula string ("=<amount>*GOOGLEFINANCE(\"CURRENCY:
    # <code>AUD\")") so Sheets converts it live at the current rate rather
    # than Python freezing a rate at write time — per explicit direction
    # to do currency conversion in-sheet, not in the pipeline. No match
    # found -> blank, same "blank over wrong guess" rule used everywhere
    # else in this pipeline.
    def _revenue_cell_value(self, invoice):

        if not invoice:
            return ""

        amount = invoice.get("invoice_amount", {}).get("actual")
        currency = (invoice.get("currency_code") or "").strip().upper()

        if not amount or not currency:
            return ""

        if currency == "AUD":
            return amount

        return f'={amount}*GOOGLEFINANCE("CURRENCY:{currency}AUD")'

    def _workflow_status(self, doc_type, agentcis):

        if not agentcis:
            return "Application not created"

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

        if doc_type == "art_lodgement_stage1":

            if status == "in progress" and (
                "lodgement" in stage or "outcome" in stage
            ):
                return "Yes"

            return "No"

        if doc_type == "art_outcome":

            if status == "completed":
                return "Yes"

            return "No"

        if doc_type == "skills_lodgement":

            if status == "in progress" and (
                "lodgement" in stage or "outcome" in stage
            ):
                return "Yes"

            return "No"

        if doc_type == "skills_outcome":

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

                "Email Date":
                    self._format_email_date(email_meta.get("date")),

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId"),

                "Consultant":
                    consultant_name,

                "Visa Type":
                    self._normalize_visa_type_for_dropdown(doc.get("main_visa_being_processed")),

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
        # HEALTH EXAMINATION
        # ==============================

        if doc_type == "health_examination":
            primary = doc.get("primary_applicant", {}) or {}
            primary_name = primary.get("name") or ""
            agentcis_name = agentcis_data.get("clientName") or ""

            final_name = self._build_name_block(primary_name, [], agentcis_name)

            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Email Date":
                    self._format_email_date(email_meta.get("date")),

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId"),

                "Consultant":
                    consultant_name,

                "Visa Type":
                    self._normalize_visa_type_for_dropdown(doc.get("visa_program")),

                "Transaction Reference\nNumber":
                    doc.get("transaction_reference_number"),

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId"),

                "Email Handled Date":
                    handled_date,

                "Comments/ Notes":
                    ""
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        # ==============================
        # S57 (Invitation to comment on information / Natural Justice)
        # ==============================

        if doc_type == "s57":
            primary = doc.get("primary_applicant", {}) or {}
            primary_name = primary.get("name") or ""
            agentcis_name = agentcis_data.get("clientName") or ""

            final_name = self._build_name_block(primary_name, [], agentcis_name)

            request_date_raw = doc.get("date")
            request_date = self._format_doc_date(request_date_raw)

            last_date = self._calculate_last_date(
                request_date_raw,
                doc.get("days_to_respond")
            )

            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Request Date":
                    request_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId"),

                "Consultant":
                    consultant_name,

                "Visa Type":
                    self._normalize_visa_type_for_dropdown(doc.get("visa_program")),

                "Transaction Reference\nNumber":
                    doc.get("transaction_reference_number"),

                "Email Handled Date":
                    handled_date,

                "Last Date for Submission":
                    last_date,

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

        # ==============================
        # S64 (Request for 2nd VAC)
        # ==============================

        if doc_type == "s64":
            primary = doc.get("primary_applicant", {}) or {}
            primary_name = primary.get("name") or ""
            agentcis_name = agentcis_data.get("clientName") or ""

            final_name = self._build_name_block(primary_name, [], agentcis_name)

            request_date_raw = doc.get("date")
            request_date = self._format_doc_date(request_date_raw)

            last_date = self._calculate_last_date(
                request_date_raw,
                doc.get("days_to_respond")
            )

            sponsor = doc.get("sponsor")
            info_request = f"Second VAC payment required{f' — sponsor: {sponsor}' if sponsor else ''}"

            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Email Received":
                    handled_date,

                "Request Date":
                    request_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId"),

                "Consultant":
                    consultant_name,

                "Visa Type":
                    self._normalize_visa_type_for_dropdown(doc.get("visa_program")),

                "Transaction Reference\nNumber":
                    doc.get("transaction_reference_number"),

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId"),

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

        # ==============================
        # CITIZENSHIP APPOINTMENT LETTER
        # ==============================

        if doc_type == "citizenship_appointment":
            primary = doc.get("primary_applicant", {}) or {}
            primary_name = primary.get("name") or ""
            agentcis_name = agentcis_data.get("clientName") or ""

            final_name = self._build_name_block(primary_name, [], agentcis_name)

            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            appointment = doc.get("appointment_date_time") or ""
            place = doc.get("appointment_place") or ""
            appointment_display = f"{appointment}\n{place}".strip("\n") if place else appointment

            sheet_fields = {

                "Email Received":
                    handled_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or doc.get("client_id"),

                "Consultant":
                    consultant_name,

                "Transaction Reference\nNumber":
                    doc.get("transaction_reference_number"),

                "Email Handled Date":
                    handled_date,

                "Appointment Date & Time":
                    appointment_display,

                "Reminder Date":
                    "",

                "Comments/ Notes":
                    ""
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        # ==============================
        # NOTIFICATION (generic bucket — refund / withdrawal / assessment
        # commence / citizenship approval / general). Both "Email Handled" and
        # "Email Handled Date" are supplied since the target tabs disagree on
        # which label they use — the Apps Script's header matching keeps
        # whichever one actually exists on that tab and ignores the other.
        # ==============================

        if doc_type == "notification":
            primary_name = doc.get("name") or ""
            agentcis_name = agentcis_data.get("clientName") or ""

            final_name = self._merge_names(primary_name, agentcis_name)

            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Email Received":
                    handled_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId"),

                "Consultant":
                    consultant_name,

                "Visa Type":
                    self._normalize_visa_type_for_dropdown(doc.get("visa_program")),

                "Transaction Reference\nNumber":
                    doc.get("transaction_reference_number"),

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId"),

                "Notification":
                    doc.get("notification_text"),

                "Email Handled":
                    handled_date,

                "Email Handled Date":
                    handled_date,

                "Notification Date":
                    handled_date,

                "Comments/ Notes":
                    ""
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        # ==============================
        # ART (Administrative Review Tribunal) — separate case-ID scheme,
        # single shared spreadsheet regardless of mailbox. Stage 1 and stage
        # 2 both target the "Lodgement" tab; stage 2 doesn't have enough of
        # its own data to justify a fresh row (no online reference number,
        # Consultant/Form956/etc. all unknown from this letter alone), so it
        # returns a "match_name" alongside a minimal fields dict — the
        # orchestrator uses that to request an update-in-place (upsert) of
        # the stage 1 row rather than a plain append.
        # ==============================

        if doc_type == "art_lodgement_stage1":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            checklist = agentcis_data.get("checklist", {})
            form956 = self._normalize_checklist_value(checklist.get("Form 956"))
            client_agreement = self._normalize_checklist_value(checklist.get("Client Agreement"))
            proof_payment = self._normalize_checklist_value(checklist.get(
                "Proof of Invoice Payment (Paid/Partially Paid)"
            ))

            lodged_date = self._format_doc_date(doc.get("date"))
            workflow = self._workflow_status("art_lodgement_stage1", agentcis_data)

            sheet_fields = {

                "Email Received":
                    lodged_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Online Reference Number":
                    doc.get("online_reference_number"),

                "Case #":
                    doc.get("case_number") or "",

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Form 956":
                    form956,

                "Client Agreement":
                    client_agreement,

                "Proof of Payment":
                    proof_payment,

                "Revenue":
                    self._revenue_cell_value(agentcis_data.get("revenue_invoice")),

                "Workflow Updated on Agentcis?":
                    workflow,

                "Email Handled Date":
                    handled_date,

                "Notes/Comments":
                    f"[{lodged_date}] Lodgement Acknowledgement" if lodged_date else "Lodgement Acknowledgement",

                "Week Range":
                    self._compute_week_range()
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        if doc_type == "art_lodgement_stage2":

            primary = doc.get("primary_applicant", {}) or {}
            applicant_name = primary.get("name") or ""

            letter_date = self._format_doc_date(doc.get("date"))

            sheet_fields = {

                "Case #":
                    doc.get("case_number") or "",

                "Email Handled Date":
                    handled_date,

                "Notes/Comments":
                    f"[{letter_date}] Acknowledgement of Application" if letter_date else "Acknowledgement of Application",
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields,
                "match_name": applicant_name,
            }

        if doc_type == "art_outcome":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            outcome_date = self._format_doc_date(doc.get("date"))
            workflow = self._workflow_status("art_outcome", agentcis_data)

            sheet_fields = {

                "Email Received":
                    outcome_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Case #":
                    doc.get("case_number") or "",

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Outcome":
                    doc.get("outcome") or "",

                "Workflow Updated on Agentcis?":
                    workflow,

                "Email Handled Date":
                    handled_date,

                "Notes/Comments":
                    "",

                "Week Range":
                    self._compute_week_range()
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        if doc_type == "art_notice_of_hearing":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Email Date":
                    self._format_doc_date(doc.get("date")),

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Case #":
                    doc.get("case_number") or "",

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Hearing Details":
                    doc.get("hearing_details") or "",

                "Comments/Notes":
                    "",
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        if doc_type == "art_notification":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Email Received":
                    handled_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Online Reference Number":
                    doc.get("online_reference_number"),

                "Case #":
                    doc.get("case_number") or "",

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Notification":
                    doc.get("notification_text"),

                "Comments/Notes":
                    "",
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        # ==============================
        # SKILLS ASSESSMENT (VETASSESS / EA / TRA) — one shared spreadsheet
        # regardless of mailbox. `doc.get("authority")` is always set
        # explicitly by SkillsExtractor; `doc.get("partner_application_id")`
        # is each authority's own reference (VETASSESS ref / EA Application
        # ID / TRA ref), always populated into transaction_reference_number
        # too so business_rules.py's existing TRN-based grouping works
        # unchanged.
        # ==============================

        if doc_type == "skills_lodgement":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            checklist = agentcis_data.get("checklist", {})
            form956 = self._normalize_checklist_value(checklist.get("Form 956"))
            client_agreement = self._normalize_checklist_value(checklist.get("Client Agreement"))
            proof_payment = self._normalize_checklist_value(checklist.get(
                "Proof of Invoice Payment (Paid/Partially Paid)"
            ))

            sheet_fields = {

                "Email Received":
                    handled_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Partner Application ID":
                    doc.get("partner_application_id"),

                "Skills Assessment Authority":
                    doc.get("authority"),

                "Form 956":
                    form956,

                "Client Agreement":
                    client_agreement,

                "Proof of Payment":
                    proof_payment,

                "Revenue":
                    self._revenue_cell_value(agentcis_data.get("revenue_invoice")),

                "Workflow Updated on Agentcis?":
                    self._workflow_status("skills_lodgement", agentcis_data),

                "Email Handled Date":
                    handled_date,

                "Notes":
                    "",

                "Week Range":
                    self._compute_week_range()
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        if doc_type == "skills_outcome":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            outcome_date_raw = doc.get("outcome_date")
            outcome_date = self._format_doc_date(outcome_date_raw) if outcome_date_raw else handled_date

            # Only TRA's PSA pathway is reliably distinguishable from what
            # we extract — VETASSESS/EA don't give a clean signal for "Full
            # Skills Assessment" vs "Qualifications Only", so left blank
            # rather than guessed.
            assessment_type = "Provisional Skills Assessment" if doc.get("authority") == "TRA" else ""

            sheet_fields = {

                "Email Received":
                    handled_date,

                "Outcome Date":
                    outcome_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Partner Application ID":
                    doc.get("partner_application_id"),

                "Skills Assessment Authority":
                    doc.get("authority"),

                "Assessment Type":
                    assessment_type,

                "Outcome":
                    doc.get("outcome") or "",

                "Occupation":
                    doc.get("occupation") or "",

                "Workflow Updated on Agentcis?":
                    self._workflow_status("skills_outcome", agentcis_data),

                "Email Handled Date":
                    handled_date,

                "Comments/Notes":
                    "",

                "Week Range":
                    self._compute_week_range()
            }

            result = {
                "document_type": doc_type,
                "fields": sheet_fields
            }

            # Approvals Expiry is filled in manually by staff, never by the
            # pipeline — no companion row is generated here.
            return result

        if doc_type == "skills_request_info":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            last_date = ""
            deadline_raw = doc.get("deadline_raw")
            if deadline_raw and re.match(r"^\d{1,2}\s+\w+\s+\d{4}$", deadline_raw):
                last_date = self._format_doc_date(deadline_raw)

            sheet_fields = {

                "Email Received":
                    handled_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Partner Application ID":
                    doc.get("partner_application_id"),

                "Skills Assessment Authority":
                    doc.get("authority"),

                # Left blank on request — staff read the actual email
                # rather than relying on the auto-extracted text here.
                "Information Request":
                    "",

                "Last Date of Submission":
                    last_date,

                "Email Handled Date":
                    handled_date,

                "Handled?":
                    "",

                "Comments/Notes":
                    "",
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        if doc_type == "skills_notification":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Notification Date":
                    handled_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Partner Application ID":
                    doc.get("partner_application_id"),

                "Skills Assessment Authority":
                    doc.get("authority"),

                "Notification":
                    doc.get("notification_text"),

                "Email Handled Date":
                    handled_date,

                "Comments/Notes":
                    "",
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        if doc_type == "skills_jrp_notification":

            final_name = self._art_final_name(doc, agentcis_data)
            consultant_name = self._detect_consultant_from_cc(email_meta)
            if not consultant_name:
                consultant_name = agentcis_data.get("assignee")

            sheet_fields = {

                "Email Received":
                    handled_date,

                "Client Name \n(Agentcis Client Name)":
                    final_name,

                "Client ID":
                    agentcis_data.get("internalId") or "",

                "Consultant":
                    consultant_name,

                "Agentcis Application\nID":
                    agentcis_data.get("applicationId") or "",

                "Partner Application ID":
                    doc.get("partner_application_id"),

                "Notification Type":
                    doc.get("notification_type"),

                "Email Handled Date":
                    handled_date,

                "Comments/Notes":
                    "",
            }

            return {
                "document_type": doc_type,
                "fields": sheet_fields
            }

        # ==============================
        # GRANT
        # ==============================

        if doc_type in self.IMMI_OUTCOME_LABELS:
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
                    self.IMMI_OUTCOME_LABELS[doc_type],

                "Workflow Updated on Agentcis":
                    workflow,

                "Email Handled Date":
                    handled_date,

                "Comments/ Notes":
                    "",

                "Week Range":
                    self._compute_week_range()
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

        form956 = self._normalize_checklist_value(checklist.get("Form 956"))
        client_agreement = self._normalize_checklist_value(checklist.get("Client Agreement"))
        proof_payment = self._normalize_checklist_value(checklist.get(
            "Proof of Invoice Payment (Paid/Partially Paid)"
        ))

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
                agentcis_data.get("internalId") or "",

            "Consultant":
                consultant_name,

            "Visa Type":
                self._resolve_visa_type(doc, subject),

            "Transaction Reference\nNumber":
                doc.get("transaction_reference_number"),

            "Agentcis Application\nID":
                agentcis_data.get("applicationId") or "",

            "Form 956":
                form956,

            "Client Agreement":
                client_agreement,

            "Proof of Payment":
                proof_payment,

            "Revenue":
                self._revenue_cell_value(agentcis_data.get("revenue_invoice")),

            "Workflow Updated on Agentcis":
                workflow,

            "Email Handled Date":
                handled_date,

            "Comments/ Notes":
                "",

            "Week Range":
                self._compute_week_range()
        }

        return {
            "document_type": doc_type,
            "fields": sheet_fields
        }
