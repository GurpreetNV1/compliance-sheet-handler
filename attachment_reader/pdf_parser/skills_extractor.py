import json
import os
import re
from datetime import datetime, timedelta


# Editable, code-free mapping of "subject contains X" -> which tab an email
# should go to (or "ignore" for forwarded-but-noise emails that should
# never create a sheet entry at all). Added after a real TRA notification
# got mislabeled EA and a real payment-receipt email that should have been
# a Lodgement entry landed in Notifications instead — rather than keep
# patching scattered regex logic, subject-based routing now lives here so
# new/corrected patterns can be added without touching this file. Checked
# FIRST in detect_document_type(); the hardcoded logic below only runs for
# subjects this file doesn't cover (mostly body-only signals, like
# VETASSESS's outcome letters, which have no reliable subject pattern at
# all). Strictly subject-only, per direct instruction — never matched
# against email body text.
_SUBJECT_RULES_PATH = os.path.join(os.path.dirname(__file__), "skills_subject_rules.jsonc")
_SUBJECT_RULES_CACHE = None

_SUBJECT_RULE_TAB_TO_DOC_TYPE = {
    "lodgement": "skills_lodgement",
    "outcome": "skills_outcome",
    "request_info": "skills_request_info",
    "notification": "skills_notification",
    "jrp": "skills_jrp_notification",
    "ignore": "unknown",
}


def _load_subject_rules():
    global _SUBJECT_RULES_CACHE
    if _SUBJECT_RULES_CACHE is None:
        try:
            with open(_SUBJECT_RULES_PATH, "r", encoding="utf-8") as f:
                raw = f.read()
            # The file is meant to be hand-edited and grouped with "// Authority"
            # comment headers for readability — plain JSON doesn't support
            # comments, so full-line "//" comments are stripped before parsing.
            # None of the rule text itself needs "//", so this is safe.
            json_text = re.sub(r"^\s*//.*$", "", raw, flags=re.MULTILINE)
            _SUBJECT_RULES_CACHE = json.loads(json_text)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"skills_subject_rules.json not loaded ({e}) — falling back to hardcoded detection only")
            _SUBJECT_RULES_CACHE = []
    return _SUBJECT_RULES_CACHE


def _subject_rule_matches(rule, subject):
    # Real subjects have inconsistent spacing (a genuine VETASSESS example
    # has "Received  Documentation" with a double space) — whitespace is
    # collapsed on both sides before comparing so a rule's exact text
    # doesn't silently fail to match a real subject over one extra space.
    subject_flat = re.sub(r"\s+", " ", subject).lower()

    contains = rule.get("subject_contains")
    if contains:
        if isinstance(contains, str):
            contains = [contains]
        if not all(re.sub(r"\s+", " ", c).lower() in subject_flat for c in contains):
            return False

    pattern = rule.get("subject_regex")
    if pattern and not re.search(pattern, subject):
        return False

    return bool(contains or pattern)


def _match_subject_rules(subject):
    for rule in _load_subject_rules():
        if _subject_rule_matches(rule, subject):
            return _SUBJECT_RULE_TAB_TO_DOC_TYPE.get(rule.get("tab"), "unknown")
    return None


_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


class SkillsExtractor:
    """
    Skills Assessment authorities (VETASSESS, EA, TRA, ACECQA, ACS, AIQS,
    AITSL, ANMAC, AQATO, CA ANZ) — a completely different case-ID scheme
    (Partner Application ID / EA ID / TRA ref / AFA number / ...) and
    institution set from everything IMMIExtractor handles, so this is a
    separate class rather than more methods bolted onto that file.
    processor.py tries IMMIExtractor first; this is the fallback when that
    returns "unknown".

    Real source emails render as markdown-bold ("*Applicant's Name: X*")
    once converted from HTML to plain text — asterisks carry no real
    meaning in any of these templates, so they're stripped up front rather
    than worked around in every regex.
    """

    def __init__(self, text: str, subject: str = None, filename: str = None):
        self.text = (text or "").replace("*", "")
        self.subject = (subject or "").replace("*", "")
        # Some authorities (ACS) only reveal Positive/Negative in the PDF's
        # own filename, not any extractable body/PDF text — see ACS branch.
        self.filename = filename or ""
        # Subject-line data (e.g. Application IDs that only appear in the
        # subject, not the body) needs to be searchable the same way as
        # body text — treated as a leading line of the same document.
        self.full_text = f"{self.subject}\n{self.text}"
        # Whitespace-flattened for plain multi-word substring trigger
        # checks — real source text wraps mid-phrase ("MSA CDR\nApplication
        # for"), which a literal-space `in` check would otherwise miss.
        self.flat = re.sub(r"\s+", " ", self.full_text)

    def _clean(self, value):
        if not value:
            return None
        return re.sub(r"\s+", " ", value).strip()

    def _clean_date(self, value):
        # VETASSESS renders dates as "31 December, 2025" — the comma breaks
        # the "%d %B %Y" parser every other extractor in this codebase
        # relies on, so it's stripped here at the source.
        cleaned = self._clean(value)
        if not cleaned:
            return None
        return cleaned.replace(",", "")

    def _reformat_dmy(self, value):
        # ANMAC's Letter of Determination states dates as "1/3/2024"
        # (D/M/YYYY) rather than the "31 December 2025" convention every
        # other authority/extractor in this codebase uses — reformatted
        # here at the source so field_mapper's _format_doc_date (which only
        # understands "%d %B %Y") handles it the same as everything else.
        if not value:
            return None
        try:
            dt = datetime.strptime(value.strip(), "%d/%m/%Y")
            return dt.strftime("%d %B %Y")
        except ValueError:
            return None

    def _word_to_years(self, value):
        if not value:
            return None
        value = value.strip().lower()
        if value.isdigit():
            return int(value)
        return _WORD_NUMBERS.get(value)

    def _dedupe_doubled_name(self, name):
        # ANMAC's own mail-merge sometimes concatenates first+last name
        # twice with no separator ("Sukhjinder KaurSukhjinder Kaur") — a
        # real template bug on their end, not something to capture verbatim.
        if not name:
            return name
        n = len(name)
        if n % 2 == 0 and name[: n // 2] == name[n // 2:]:
            return name[: n // 2]
        return name

    def _section(self, start_keyword, end_keyword=None):
        if end_keyword:
            pattern = rf"{start_keyword}(.*?){end_keyword}"
        else:
            pattern = rf"{start_keyword}(.*)"
        match = re.search(pattern, self.full_text, re.DOTALL | re.IGNORECASE)
        return match.group(1) if match else None

    # ==============================================================
    # DOCUMENT TYPE DETECTION
    # ==============================================================

    def detect_document_type(self):

        subject_rule_match = _match_subject_rules(self.subject)
        if subject_rule_match:
            return subject_rule_match

        flat = self.flat
        flat_lower = flat.lower()
        subject_upper = self.subject.upper()
        filename_lower = self.filename.lower()

        # ---------- VETASSESS ----------
        if "VETASSESS - Application Received" in flat:
            return "skills_lodgement"
        if "VETASSESS - Received" in flat and "Documentation" in flat:
            return "skills_lodgement"
        if "Reference number:" in flat and "Nominated occupation:" in flat and "Outcome:" in flat:
            return "skills_outcome"
        if "VETASSESS" in flat and "Outstanding Documentation" in flat:
            return "skills_request_info"
        if "Additional Documents -" in self.subject and "vetassess" in flat_lower:
            return "skills_request_info"
        if "Reminder notice for incomplete application" in flat:
            return "skills_request_info"
        if "PRIORITY PROCESSING REQUEST" in flat:
            return "skills_notification"
        if "Your payment to VETASSESS" in flat:
            return "skills_notification"
        if "VETASSESS File Reference" in self.subject:
            return "skills_notification"

        # ---------- EA (Engineers Australia) ----------
        if "the MSA CDR Application for" in flat and "has been submitted to Engineers Australia for assessment" in flat:
            return "skills_lodgement"
        if "Engineers Australia Account Created" in self.subject:
            return "skills_notification"
        if "Review Agent Authorisation" in self.subject:
            return "skills_notification"
        if "meets the current requirement for the following occupation" in flat:
            return "skills_outcome"
        if "does not meet the minimum requirement to confer standing" in flat:
            return "skills_outcome"
        if "Application Cancelled" in self.subject and "EA ID" in self.subject:
            return "skills_outcome"
        if "Request for Additional Information" in self.subject and "Engineers Australia" in self.subject:
            return "skills_request_info"
        if "Additional Information Request Expired" in self.subject:
            return "skills_notification"

        # ---------- ACECQA ----------
        if "accepted by acecqa as being complete" in flat_lower:
            return "skills_lodgement"
        if "assessed as suitable for the nominated occupation" in flat_lower:
            return "skills_outcome"
        if "assessed as not suitable for the nominated occupation" in flat_lower:
            return "skills_outcome"
        if "assessed your qualification as not equivalent" in flat_lower:
            return "skills_outcome"
        if "Incomplete application" in self.subject and "acecqa" in flat_lower:
            return "skills_request_info"
        if "Further information request" in self.subject and "Case number" in self.flat:
            return "skills_request_info"
        if ("Your payment to ACECQA" in flat or "Payment of your ACECQA Skills Assessment Application" in flat
                or "Request to clarify" in self.subject and "acecqa" in flat_lower):
            return "skills_notification"

        # ---------- ACS (Australian Computer Society) ----------
        if "ACS Migration Skill Assessment Payment Receipt" in self.subject:
            return "skills_lodgement"
        if re.search(r"ACS Skills Assessment Result for .+ - Ref \[A-\d{6}\]", self.subject):
            return "skills_outcome"
        if "result letter" in filename_lower and "acs" in flat_lower:
            return "skills_outcome"
        if re.search(r"Email Missing Documents Ref (A-\d{6}|ACS-\d{7})", self.subject):
            return "skills_request_info"
        if "Migration Agent Authorisation Request" in self.subject and "acs.org.au" in flat_lower:
            return "skills_notification"
        if "Migration Agent De-authorisation Request" in self.subject:
            return "skills_notification"
        if "New Message from ACS Skills Migration Assessment Team" in self.subject:
            return "skills_notification"
        if "ACS Skills Migration Assessment Outcome" in self.subject:
            return "skills_notification"
        if "Cancellation" in self.subject and "Refund" in self.subject and ("ACS-" in self.subject or "A-" in self.subject):
            return "skills_notification"

        # ---------- AIQS (Australian Institute of Quantity Surveyors) ----------
        # Keyed on real PDF-body markers specific to AIQS's own letter, not
        # the outer email's subject wording — a real subject/body mismatch
        # was found during research (an agent's copy-paste error sent an
        # actual ANMAC letter under an "AIQS" subject line), so detection
        # must trust the attached letter's own content, not the label.
        if "migration assessment no:" in flat_lower and "applicant no:" in flat_lower:
            return "skills_outcome"
        if "quantity surveyor" in flat_lower and re.search(r"\bosca\s*\d+", flat_lower) and "suitable" in flat_lower:
            return "skills_outcome"

        # ---------- AITSL (Australian Institute for Teaching and School Leadership) ----------
        if "for a skills assessment has been successfully submitted" in flat_lower:
            return "skills_lodgement"
        if "skills assessment: request for information" in flat_lower:
            return "skills_request_info"
        if "notification email from aitsl" in flat_lower:
            return "skills_notification"
        if "your assessment has been finalised" in flat_lower and "aitsl" in flat_lower:
            return "skills_notification"
        if ("payment request" in flat_lower or "payment received" in flat_lower) and "aitsl" in flat_lower:
            return "skills_notification"

        # ---------- ANMAC ----------
        if "thank you for your application for a migration skills assessment" in flat_lower:
            return "skills_lodgement"
        if "ANMAC Skills Assessment - Application Approved" in self.subject:
            return "skills_outcome"
        if ("More information required" in self.subject or "Additional ID Documents" in self.subject
                or "SMS - GradReady" in self.subject) and "anmac.org.au" in flat_lower:
            return "skills_request_info"
        if "ANMAC Ltd.: Cash Sale" in self.subject:
            return "skills_notification"
        if "Passport Expiring" in self.subject and "anmac" in flat_lower:
            return "skills_notification"

        # ---------- AQATO (ATTC-facilitated TRA OSAP/TSS trades channel) ----------
        aqato_context = "aqato" in flat_lower or "attc" in flat_lower or "australian trade training college" in flat_lower
        if "APPLICATION RECEIVED (STAGE 1)" in subject_upper and (aqato_context or "PRN:" in self.subject):
            return "skills_lodgement"
        if aqato_context and ("Skills Assessment Result" in self.subject or "APPLICATION CLOSED" in subject_upper
                               or "WITHDRAWN" in subject_upper or "Declined" in self.subject):
            return "skills_outcome"
        if aqato_context and "REINSTATED" in subject_upper:
            return "skills_notification"
        if aqato_context and ("ACTION REQUIRED (STAGE 1)" in subject_upper
                               or "Request outstanding information" in self.subject
                               or "Request additional information" in self.subject):
            return "skills_request_info"
        if aqato_context and ("TECHNICAL INTERVIEW" in subject_upper or "Payment Details" in self.subject
                               or "Employment Verification Pending" in self.subject):
            return "skills_notification"

        # ---------- CA ANZ (Chartered Accountants Australia and New Zealand) ----------
        if "your migration skills assessment application has been received" in flat_lower and "afa-" in flat_lower:
            return "skills_lodgement"
        if "Skilled Employment" in self.subject and "AFA-" in self.subject:
            return "skills_notification"
        if "ca anz migration skills assessment - assessment complete" in flat_lower:
            return "skills_outcome"
        if ("ca anz migration skills assessment - syllabus required" in flat_lower
                or "ca anz migration skills assessment - further information required" in flat_lower):
            return "skills_request_info"
        if "Tax invoice from Chartered Accountants Australia and New Zealand" in self.subject:
            return "skills_notification"
        if "CA ANZ Auto Response" in self.subject:
            return "skills_notification"
        if "authorised you to continue with the migration skills assessment application" in flat_lower:
            return "skills_notification"

        # ---------- TRA (Trades Recognition Australia) ----------
        if "Acknowledgement of Application for Assessment" in flat:
            return "skills_lodgement"
        if "PROVISIONAL SKILLS ASSESSMENT (PSA) - OUTCOME" in subject_upper:
            return "skills_outcome"
        if "PSA VERIFICATION REQUEST" in subject_upper or "PSA - ADDITIONAL" in subject_upper:
            return "skills_request_info"
        if "IMPORTANT INFORMATION relating to your TRA Provisional Skills Assessment" in flat:
            return "skills_request_info"
        if "Payment Receipt" in self.subject and ("TRA" in flat or "ssc.gov.au" in flat):
            return "skills_notification"

        # JRP lifecycle — one generic bucket, trigger phrases match the real
        # subjects/headings found across the ~9 real stages.
        jrp_triggers = [
            "Job Ready Program - Agent Nomination Form",
            "Job Ready Program - Agent/Individual Not Authorised",
            "Job Ready Employment - Outcome",
            "Job Ready Program - JRE - Registration Eligible",
            "Job Ready Program - JRE - Additional Documents Required",
            "Job Ready Program - Additional Information Required",
            "Job Ready Workplace Assessment Invitation",
            "Job Ready Workplace Application Progress",
            "Job Ready Workplace Assessment Outcome - Not Yet Job Ready",
            "Your Job Ready Workplace Assessment Outcome was Job Ready",
            "Job Ready Final Assessment Invite",
            "JRFA Invite",
            "JRFA Outcome",
            "Job Ready Program Application Is Inactive",
            "Job Ready Program Application is about to become inactive",
            "Changes to your JRFA Date",
        ]
        if any(t.lower() in flat_lower for t in jrp_triggers):
            return "skills_jrp_notification"

        return "unknown"

    # ==============================================================
    # Shared helpers
    # ==============================================================

    def _find_ref(self):
        # TRA../888.../999... and VETASSESS's 2-letter-code refs share a
        # loose enough shape that one pattern covers both; EA's numeric
        # Application ID is handled separately where needed.
        m = re.search(r"\bTRA\d{2}/\d{6,10}\b", self.full_text)
        if m:
            return m.group(0)
        m = re.search(r"\b\d{2}[A-Z]{2}\d{6}\b", self.full_text)
        if m:
            return m.group(0)
        return None

    def _applicants_name(self):
        m = re.search(r"Applicant.s Name:\s*(.+)", self.full_text)
        return self._clean(m.group(1)) if m else None

    def _applicant_email(self):
        m = re.search(r"Applicant Email:\s*(\S+@\S+)", self.full_text)
        return self._clean(m.group(1)) if m else None

    def _dear_name(self):
        m = re.search(r"Dear\s+(.+?)[,\n]", self.full_text)
        return self._clean(m.group(1)) if m else None

    def _acs_ref(self):
        m = re.search(r"\bACS-\d{7}\b", self.full_text)
        if m:
            return m.group(0)
        m = re.search(r"\bA-\d{6}\b", self.full_text)
        if m:
            return m.group(0)
        return None

    def _aqato_ref(self):
        m = re.search(r"\[#(\d{6,7})\]", self.full_text)
        if m:
            return m.group(1)
        m = re.search(r"\b\d{2}AQ\d{5,7}\b", self.full_text)
        if m:
            return m.group(0)
        tra_ref = self._find_ref()
        if tra_ref:
            return tra_ref
        return None

    def _aqato_name(self):
        # AQATO subjects have no single fixed shape across stages — best
        # effort: strip a leading Fwd:/Re: prefix, split on " - ", and pick
        # the first segment that reads like a name (has a space, isn't one
        # of the fixed stage-label words, and isn't a bracketed reference
        # number).
        subject = re.sub(r"^(Fwd|Fw|Re):\s*", "", self.subject, flags=re.IGNORECASE)
        segments = [s.strip() for s in re.split(r"\s+-\s+", subject) if s.strip()]
        noise = ("STAGE", "APPLICATION", "SKILLS ASSESSMENT", "OSAP", "REQUIRED",
                  "RESULT", "CLOSED", "WITHDRAWN", "DECLINED", "REINSTATED", "ACTION",
                  "EMPLOYMENT", "VERIFICATION", "PENDING", "TECHNICAL", "INTERVIEW",
                  "DOCUMENT", "TRADES RECOGNITION", "SCHEDULED", "PROGRESS", "INVITE",
                  "INVITATION", "PAYMENT")
        for seg in segments:
            upper = seg.upper()
            if any(n in upper for n in noise):
                continue
            if re.search(r"[\[\]#]", seg):
                continue
            if seg.startswith("("):
                continue
            if len(seg.split()) >= 2:
                return self._clean(re.sub(r"\(.*?\)", "", seg))
        return None

    # ==============================================================
    # Lodgement
    # ==============================================================

    def extract_skills_lodgement(self):

        # VETASSESS — ref is in the subject line for both variants.
        if "vetassess" in self.full_text.lower() or "VETASSESS" in self.subject:
            ref = self._find_ref()
            name = self._applicants_name()
            return {
                "document_type": "skills_lodgement",
                "authority": "VETASSESS",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": ref,
            }

        # EA — "Agent Authorisation Approved" is the only lodgement trigger
        # kept for this pass (see plan: Account Created / Review Agent
        # Authorisation are logged as Notifications instead).
        if "MSA CDR Application for" in self.flat:
            name_match = re.search(r"MSA CDR Application for\s+(.+?)\s+has been submitted", self.flat)
            app_id_match = re.search(r"Application:\s*(\d+)", self.subject)
            name = self._clean(name_match.group(1)) if name_match else None
            app_id = app_id_match.group(1) if app_id_match else None
            return {
                "document_type": "skills_lodgement",
                "authority": "EA",
                "partner_application_id": app_id,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": app_id,
            }

        # EA — "Review Agent Authorisation" uses different real wording than
        # "Agent Authorisation Approved" above (lowercase "application", an
        # Application Id in parentheses, "on behalf of {Name}" instead of
        # "for {Name} has been submitted"). Previously unhandled, so it fell
        # through to the generic TRA fallback at the bottom of this method —
        # mislabeling a real EA case as authority "TRA" with a blank name
        # and reference (confirmed live: Pujan Patel's and Sahil Kumar's
        # real "Review Agent Authorisation" emails, Application Ids
        # 655759/655761).
        if "msa cdr application" in self.flat.lower() and "on behalf of" in self.flat.lower():
            app_id_match = re.search(r"Application Id\s*:\s*(\d+)", self.flat, re.IGNORECASE)
            name_match = re.search(r"on behalf of\s+(.+?)\.", self.flat, re.IGNORECASE)
            app_id = app_id_match.group(1) if app_id_match else None
            name = self._clean(name_match.group(1)) if name_match else None
            return {
                "document_type": "skills_lodgement",
                "authority": "EA",
                "partner_application_id": app_id,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": app_id,
            }

        # ACECQA — case number sometimes zero-padded inconsistently across
        # a case's own lifecycle ("445015" vs "00445015") — normalized by
        # stripping leading zeros so skills_lookup.py's cross-reference
        # matching still works across stages.
        if "acecqa" in self.full_text.lower():
            ref_match = re.search(r"[Cc]ase number:?\s*(\d+)", self.full_text)
            ref = str(int(ref_match.group(1))) if ref_match else None
            name = self._dear_name()
            return {
                "document_type": "skills_lodgement",
                "authority": "ACECQA",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": ref,
            }

        # ACS — the payment-receipt email salutes the agent ("Dear Robin"),
        # not the client, so name is deliberately left unset rather than
        # mis-captured as a staff member's name.
        if "acs" in self.full_text.lower() and re.search(r"ref\s+(A-\d{6}|ACS-\d{7})", self.full_text, re.IGNORECASE):
            ref = self._acs_ref()
            return {
                "document_type": "skills_lodgement",
                "authority": "ACS",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": ref,
            }

        # AITSL — two reference eras: legacy SAMS, and new 8-char hex IDs.
        if "aitsl" in self.full_text.lower() or "successfully submitted" in self.flat.lower():
            ref_match = re.search(r"\bSAMS\d{9,10}\b", self.full_text) or \
                re.search(r"reference:\s*([0-9a-fA-F]{8})\b", self.full_text)
            ref = ref_match.group(1) if ref_match and ref_match.lastindex else (
                ref_match.group(0) if ref_match else None
            )
            name_match = re.search(r"Applicant name:\s*(.+)", self.full_text) or \
                re.search(r"Full name:\s*(.+)", self.full_text)
            name = self._clean(name_match.group(1)) if name_match else None
            return {
                "document_type": "skills_lodgement",
                "authority": "AITSL",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": ref,
            }

        # ANMAC — real mail-merge sometimes doubles the salutation name.
        # Requires "anmac" explicitly (not just the generic "migration
        # skills assessment" + "reference number" phrasing) — CA ANZ's own
        # lodgement email also says "migration skills assessment" and was
        # found to falsely match this branch without the explicit check.
        if "anmac" in self.full_text.lower() and "reference number" in self.flat.lower():
            ref_match = re.search(r"Reference Number:?\s*(?:&nbsp;)?\s*(\d{6})", self.full_text, re.IGNORECASE)
            ref = ref_match.group(1) if ref_match else None
            name = self._dedupe_doubled_name(self._dear_name())
            return {
                "document_type": "skills_lodgement",
                "authority": "ANMAC",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": ref,
            }

        # AQATO (ATTC-facilitated OSAP/TSS trades intake)
        if "aqato" in self.full_text.lower() or "attc" in self.full_text.lower():
            ref = self._aqato_ref()
            name = self._aqato_name()
            return {
                "document_type": "skills_lodgement",
                "authority": "AQATO",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": ref,
            }

        # CA ANZ
        if "ca anz" in self.full_text.lower() or "afa-" in self.full_text.lower():
            ref_match = re.search(r"\bAFA-\d{6}\b", self.full_text)
            ref = ref_match.group(0) if ref_match else None
            name_match = re.search(r"Application you lodged for\s+(.+?)\s+was received", self.full_text)
            name = self._clean(name_match.group(1)) if name_match else None
            return {
                "document_type": "skills_lodgement",
                "authority": "CA ANZ",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "transaction_reference_number": ref,
            }

        # TRA — the real Payment Receipt template ("{NAME} - TRA26/XXXXX -
        # Payment Receipt ...") states both the applicant's name AND email
        # directly in the body ("Applicant Name: ...", "Applicant Email:
        # ..."). This is the ONE Skills authority where the client's own
        # email is reliably present at all (per explicit user direction),
        # so it's captured here and used for a direct Agentcis search
        # rather than relying on the (usually all-internal-staff)
        # recipients list. Falls back to the older subject-based pattern
        # ("Migration Skills Assessment TRA ... TRA../......") for the
        # template that doesn't include an Applicant Name/Email block.
        ref = self._find_ref()
        applicant_email = self._applicant_email()
        name_match = re.search(r"Applicant Name:\s*(.+)", self.full_text) or \
            re.search(r"Migration Skills Assessment TRA\s+(.+?)\s+TRA\d{2}/", self.subject)
        name = self._clean(name_match.group(1)) if name_match else None
        return {
            "document_type": "skills_lodgement",
            "authority": "TRA",
            "partner_application_id": ref,
            "name": name,
            "primary_applicant": {"name": name, "dob": None},
            "secondary_applicants": [],
            "applicant_email": applicant_email,
            "transaction_reference_number": ref,
        }

    # ==============================================================
    # Outcome
    # ==============================================================

    def extract_skills_outcome(self):

        # VETASSESS — labeled "SKILLED MIGRATION ASSESSMENT" summary block.
        if "Nominated occupation:" in self.text:
            ref = re.search(r"Reference number:\s*([A-Z0-9]+)", self.text)
            name = re.search(r"Full name:\s*(.+)", self.text)
            occupation = re.search(r"Nominated occupation:\s*(.+?)\s*\(ANZSCO Code:\s*(\d+)\)", self.text, re.DOTALL)
            issue_date = re.search(r"Date of issue:\s*([\d]{1,2}\s+\w+,?\s+\d{4})", self.text)
            validity = re.search(r"Validity period:\s*(\d+)\s*years?", self.text)
            outcome_word = re.search(r"\bOutcome:\s*(Not Suitable|Suitable)\b", self.text)

            outcome = None
            if outcome_word:
                outcome = "Positive" if outcome_word.group(1) == "Suitable" else "Negative"

            return {
                "document_type": "skills_outcome",
                "authority": "VETASSESS",
                "partner_application_id": ref.group(1) if ref else None,
                "name": self._clean(name.group(1)) if name else None,
                "primary_applicant": {"name": self._clean(name.group(1)) if name else None, "dob": None},
                "secondary_applicants": [],
                "occupation": self._clean(occupation.group(1)) if occupation else None,
                "outcome": outcome,
                "outcome_date": self._clean_date(issue_date.group(1)) if issue_date else None,
                "validity_years": int(validity.group(1)) if validity else 3,
                "transaction_reference_number": ref.group(1) if ref else None,
            }

        # EA — Positive/Negative both confirmed against real letters.
        if "Engineers Australia" in self.text or "EA ID:" in self.text:
            ea_id = re.search(r"EA ID:\s*(\d+)", self.text)
            app_id = re.search(r"Application ID:\s*(\d+)", self.text)
            name = re.search(r"Dear\s+(.+?),", self.text)
            date = re.search(r"^\s*(\d{1,2}\s+\w+\s+\d{4})", self.text, re.MULTILINE)

            occupation_row = re.search(
                r"Skill Level\s*\d+\s+(.+?)\s+(\d{6})\s+(\S+\s+\d{4})", self.text
            )

            if occupation_row:
                outcome = "Positive"
                occupation = self._clean(occupation_row.group(1))
            elif "does not meet the minimum requirement" in self.text:
                outcome = "Negative"
                occupation = None
            else:
                outcome = None
                occupation = None

            return {
                "document_type": "skills_outcome",
                "authority": "EA",
                "partner_application_id": app_id.group(1) if app_id else None,
                "ea_id": ea_id.group(1) if ea_id else None,
                "name": self._clean(name.group(1)) if name else None,
                "primary_applicant": {"name": self._clean(name.group(1)) if name else None, "dob": None},
                "secondary_applicants": [],
                "occupation": occupation,
                "outcome": outcome,
                "outcome_date": self._clean_date(date.group(1)) if date else None,
                "validity_years": 3,
                "transaction_reference_number": app_id.group(1) if app_id else None,
            }

        # EA — Application Cancelled (no client name in this email at all;
        # relies on the Partner-Application-ID cross-reference lookup).
        if "Application Cancelled" in self.subject:
            ea_id = re.search(r"EA ID\s*:\s*(\d+)", self.subject)
            app_id = re.search(r"Application ID:\s*(\d+)", self.subject)
            return {
                "document_type": "skills_outcome",
                "authority": "EA",
                "partner_application_id": app_id.group(1) if app_id else None,
                "ea_id": ea_id.group(1) if ea_id else None,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "occupation": None,
                "outcome": "Cancelled",
                "outcome_date": None,
                "validity_years": None,
                "transaction_reference_number": app_id.group(1) if app_id else None,
            }

        # ACECQA — no real Cancelled sample found, two-way only. The "dual"
        # Skills + Qualification Assessment emails carry 2 PDFs, each
        # processed independently by processor.process_folder, so no
        # special dual-outcome handling is needed here. Condition is the
        # exact phrase (not a loose "nominated occupation" + "assessed as"
        # anywhere-in-text check) — a real ANMAC letter ("...assessed as
        # suitable for migration for the nominated occupation of...") was
        # found to satisfy the loose version, misclassifying it as ACECQA.
        if ("assessed as suitable for the nominated occupation" in self.full_text.lower()
                or "assessed as not suitable for the nominated occupation" in self.full_text.lower()
                or "assessed your qualification as not equivalent" in self.full_text.lower()):
            ref_match = re.search(r"[Cc]ase number:?\s*(\d+)", self.full_text)
            ref = str(int(ref_match.group(1))) if ref_match else None
            name = self._dear_name()
            occ_match = re.search(r"nominated occupation of\s+(.+?)(?:\s*\(ANZSCO|\.|,|\n)", self.full_text, re.IGNORECASE)
            anzsco_match = re.search(r"\(ANZSCO\s*(\d+)\)", self.full_text)
            occupation = self._clean(occ_match.group(1)) if occ_match else None
            if occupation and anzsco_match:
                occupation = f"{occupation} (ANZSCO {anzsco_match.group(1)})"

            flat_lower = self.full_text.lower()
            if "assessed as not suitable" in flat_lower or "not equivalent to the qualifications required" in flat_lower:
                outcome = "Negative"
            elif "assessed as suitable" in flat_lower:
                outcome = "Positive"
            else:
                outcome = None

            return {
                "document_type": "skills_outcome",
                "authority": "ACECQA",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "occupation": occupation,
                "outcome": outcome,
                "outcome_date": None,
                "transaction_reference_number": ref,
            }

        # ACS — real evidence for Negative is only a PDF filename containing
        # "Unsuitable"; no literal PDF body text was confirmed during
        # research, so this is explicitly best-effort/filename-based —
        # verify against a real sample during the live test.
        if "acs" in self.full_text.lower() and (self._acs_ref() or "result letter" in self.filename.lower()):
            ref = self._acs_ref()
            # Real subjects vary: "...Result for {Name} - Ref [...]" and
            # "...Result for {Name} Ref [...]" (no dash) both seen live.
            name_match = re.search(r"ACS Skills Assessment Result for\s+(.+?)\s*-?\s*Ref", self.subject)
            name = self._clean(name_match.group(1)) if name_match else None
            fname_lower = self.filename.lower()

            occ_match = re.search(r"\d{7}\s+(\d{6})\s+(.+?)\s+Result Letter", self.filename, re.IGNORECASE)
            occupation = f"{occ_match.group(2)} ({occ_match.group(1)})" if occ_match else None

            if "unsuitable" in fname_lower:
                outcome = "Negative"
            elif "result letter" in fname_lower or re.search(r"ACS Skills Assessment Result for", self.subject):
                outcome = "Positive"
            else:
                outcome = None

            return {
                "document_type": "skills_outcome",
                "authority": "ACS",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "occupation": occupation,
                "outcome": outcome,
                "outcome_date": None,
                "transaction_reference_number": ref,
            }

        # AIQS — keyed on the letter's own markers (see detect_document_type
        # comment on the real ACS/ANMAC subject-mismatch found in research).
        # Positive only — no real Negative sample. Validity confirmed as
        # "two years" in the real letter, so the companion Approvals Expiry
        # row can be written here, unlike most of the other new authorities.
        if "migration assessment no:" in self.full_text.lower() or (
                "quantity surveyor" in self.full_text.lower() and re.search(r"\bosca\s*\d+", self.full_text.lower())):
            ref_match = re.search(r"Migration Assessment No:\s*(\S+)", self.full_text, re.IGNORECASE) or \
                re.search(r"Applicant No:\s*(\d+)", self.full_text, re.IGNORECASE)
            ref = ref_match.group(1) if ref_match else None
            name = self._dear_name()
            occ_match = re.search(r"occupation of\s+(.+?)\s+OSCA\s*(\d+)", self.full_text, re.IGNORECASE)
            occupation = f"{self._clean(occ_match.group(1))} (OSCA {occ_match.group(2)})" if occ_match else None
            validity_match = re.search(r"valid for\s+(\w+)\s+years?", self.full_text, re.IGNORECASE)
            validity_years = self._word_to_years(validity_match.group(1)) if validity_match else None

            outcome = "Positive" if re.search(r"\bsuitable\b", self.full_text, re.IGNORECASE) and \
                "not suitable" not in self.full_text.lower() else None

            doc = {
                "document_type": "skills_outcome",
                "authority": "AIQS",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "occupation": occupation,
                "outcome": outcome,
                "outcome_date": None,
                "transaction_reference_number": ref,
            }
            if validity_years:
                doc["validity_years"] = validity_years
            return doc

        # ANMAC — Positive only, no real Negative/Cancelled sample. Real
        # letter states "This decision is valid for two years commencing
        # 17/2/2026" — confirmed live, so the companion Approvals Expiry
        # row is buildable. Subject-based check included alongside the body
        # markers so the body-only (no PDF text) half of a split
        # email+attachment pair is still recognized as ANMAC rather than
        # falling through to the generic TRA fallback below.
        if "ANMAC Skills Assessment - Application Approved" in self.subject or \
                ("anmac" in self.full_text.lower() and "assessed as suitable for migration" in self.full_text.lower()):
            ref_match = re.search(r"Application Approved\s*(\d{6})", self.subject) or \
                re.search(r"Reference\s*#:\s*(\d{6})", self.full_text, re.IGNORECASE)
            ref = ref_match.group(1) if ref_match else None
            # Real letter: "Reference #: 197318 {Name, sometimes wrapping
            # mid-word across a line break}\nANZSCO Code: ..."
            name_match = re.search(r"Reference #:\s*\d+\s+(.+?)ANZSCO Code:", self.full_text, re.IGNORECASE | re.DOTALL)
            name = self._clean(name_match.group(1)) if name_match else self._dedupe_doubled_name(self._dear_name())
            occ_match = re.search(r"nominated occupation of\s+(\d{6})\s+(.+?)(?:\.|,|\n)", self.full_text, re.IGNORECASE)
            occupation = f"{self._clean(occ_match.group(2))} ({occ_match.group(1)})" if occ_match else None
            date_match = re.search(r"commencing\s+(\d{1,2}/\d{1,2}/\d{4})", self.full_text, re.IGNORECASE)
            outcome_date = self._reformat_dmy(date_match.group(1)) if date_match else None
            validity_match = re.search(r"valid for\s+(\w+)\s+years?\s+commencing", self.full_text, re.IGNORECASE)
            validity_years = self._word_to_years(validity_match.group(1)) if validity_match else None

            doc = {
                "document_type": "skills_outcome",
                "authority": "ANMAC",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "occupation": occupation,
                "outcome": "Positive",
                "outcome_date": outcome_date,
                "transaction_reference_number": ref,
            }
            if validity_years:
                doc["validity_years"] = validity_years
            return doc

        # AQATO (ATTC-facilitated OSAP/TSS trades channel) — checked before
        # the generic TRA fallback below, since AQATO's outcome PDF can
        # contain a real TRA../999... reference too, which would otherwise
        # be mistaken for a plain TRA case by _find_ref().
        if "aqato" in self.full_text.lower() or "attc" in self.full_text.lower() or \
                "australian trade training college" in self.full_text.lower():
            ref = self._aqato_ref()
            name = self._aqato_name()
            subject_upper = self.subject.upper()
            flat_lower = self.full_text.lower()

            if "APPLICATION CLOSED" in subject_upper or "WITHDRAWN" in subject_upper:
                outcome = "Cancelled"
            elif "declined" in self.subject.lower() or "unsuccessful" in flat_lower:
                outcome = "Negative"
            elif "successfully completing a skills assessment" in flat_lower:
                outcome = "Positive"
            else:
                outcome = None

            return {
                "document_type": "skills_outcome",
                "authority": "AQATO",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "occupation": None,
                "outcome": outcome,
                "outcome_date": None,
                "transaction_reference_number": ref,
            }

        # CA ANZ — the covering email is identical regardless of result;
        # the real determination only exists in the PDF attachment text,
        # which renders as label-value pairs with NO colon ("Assessment
        # outcome Not suitable", "Name: Hemavathi Ravichandran" — the one
        # field that keeps its colon), confirmed against real letters.
        # Validity ("Validity period 3 years from the date of issue") and
        # date of issue are both real/confirmed too, so unlike most of the
        # other new authorities, CA ANZ's companion Approvals Expiry row
        # IS buildable. No real Cancelled sample — two-way only.
        if "ca anz" in self.full_text.lower() or re.search(r"\bAFA-\d{6}\b", self.full_text):
            ref_match = re.search(r"\bAFA-\d{6}\b", self.full_text)
            ref = ref_match.group(0) if ref_match else None
            flat_lower = self.full_text.lower()

            name_match = re.search(r"Name:\s*(.+)", self.full_text)
            name = self._clean(name_match.group(1)) if name_match else None

            occ_match = re.search(r"assessed as (?:not suitable|suitable) in the occupation of\s+(.+?)\s+(\d{6})",
                                   self.full_text, re.IGNORECASE)
            occupation = f"{self._clean(occ_match.group(1))} ({occ_match.group(2)})" if occ_match else None

            date_match = re.search(r"Date of issue\s+(\d{1,2}\s+\w+\s+\d{4})", self.full_text, re.IGNORECASE)
            outcome_date = self._clean(date_match.group(1)) if date_match else None

            validity_match = re.search(r"Validity period\s+(\d+)\s*years?", self.full_text, re.IGNORECASE)
            validity_years = int(validity_match.group(1)) if validity_match else None

            if re.search(r"assessment outcome\s+not suitable", flat_lower):
                outcome = "Negative"
            elif re.search(r"assessment outcome\s+suitable", flat_lower):
                outcome = "Positive"
            else:
                outcome = None

            doc = {
                "document_type": "skills_outcome",
                "authority": "CA ANZ",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "occupation": occupation,
                "outcome": outcome,
                "outcome_date": outcome_date,
                "transaction_reference_number": ref,
            }
            if outcome == "Positive" and validity_years:
                doc["validity_years"] = validity_years
            return doc

        # TRA — PSA Outcome
        ref = self._find_ref()
        occ = re.search(r"SUCCESSFUL for\s+(.+?)\s*-\s*(\d{6})", self.full_text, re.IGNORECASE)
        unsuccessful = "unsuccessful" in self.full_text.lower()

        name_match = re.search(r"TRA\d{2}/\d{6,10}\s*-\s*(.+)", self.subject)

        return {
            "document_type": "skills_outcome",
            "authority": "TRA",
            "partner_application_id": ref,
            "name": self._clean(name_match.group(1)) if name_match else None,
            "primary_applicant": {"name": self._clean(name_match.group(1)) if name_match else None, "dob": None},
            "secondary_applicants": [],
            "occupation": self._clean(occ.group(1)) if occ else None,
            "outcome": "Positive" if occ else ("Negative" if unsuccessful else None),
            "outcome_date": None,
            "validity_years": 3,
            "applicant_email": self._applicant_email(),
            "transaction_reference_number": ref,
        }

    # ==============================================================
    # Request for more information
    # ==============================================================

    def _extract_message_content(self, text):
        # Real Skills Assessment correspondence always arrives as an
        # internal "Fwd:" — strip the quoted "---------- Forwarded message
        # ---------" header block (From/Date/Subject/To) so the extracted
        # text starts at the actual message ("Dear ..."), and cut off at the
        # sender's sign-off/signature block rather than including their
        # name, title, phone number, and address.
        content = text

        forward_match = re.search(
            r"---------- ?Forwarded message ?---------.*?\n\s*\n", content, re.DOTALL
        )
        if forward_match:
            content = content[forward_match.end():]

        sign_off = re.search(
            r"\n\s*(Kind [Rr]egards|Yours sincerely|Best regards|Regards,)", content
        )
        if sign_off:
            content = content[:sign_off.start()]

        return content.strip()

    def extract_skills_request_info(self):

        flat_lower = self.full_text.lower()

        # ACECQA — real letter: "supply this outstanding documentation by
        # 23 July 2026" — same "by <date>" shape as VETASSESS/EA.
        if "acecqa" in flat_lower:
            ref_match = re.search(r"[Cc]ase number:?\s*(\d+)", self.full_text)
            ref = str(int(ref_match.group(1))) if ref_match else None
            name = self._dear_name()
            deadline = re.search(r"by\s+(\d{1,2}\s+\w+\s+\d{4})", self.full_text)
            return {
                "document_type": "skills_request_info",
                "authority": "ACECQA",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "information_request": self._extract_message_content(self.text)[:1500],
                "deadline_raw": deadline.group(1) if deadline else None,
                "transaction_reference_number": ref,
            }

        # ACS
        if re.search(r"Email Missing Documents Ref", self.subject, re.IGNORECASE):
            ref = self._acs_ref()
            return {
                "document_type": "skills_request_info",
                "authority": "ACS",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "information_request": self._extract_message_content(self.text)[:1500],
                "deadline_raw": None,
                "transaction_reference_number": ref,
            }

        # AITSL
        if "aitsl" in flat_lower:
            ref_match = re.search(r"request for information\s*-\s*([0-9a-fA-F]{8})", self.full_text, re.IGNORECASE)
            ref = ref_match.group(1) if ref_match else None
            deadline = re.search(r"by\s+(\d{1,2}\s+\w+\s+\d{4})", self.full_text)
            return {
                "document_type": "skills_request_info",
                "authority": "AITSL",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "information_request": self._extract_message_content(self.text)[:1500],
                "deadline_raw": deadline.group(1) if deadline else None,
                "transaction_reference_number": ref,
            }

        # ANMAC
        if "anmac" in flat_lower:
            ref_match = re.search(r"\b(\d{6})\b", self.subject)
            ref = ref_match.group(1) if ref_match else None
            name = self._dedupe_doubled_name(self._dear_name())
            return {
                "document_type": "skills_request_info",
                "authority": "ANMAC",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "information_request": self._extract_message_content(self.text)[:1500],
                "deadline_raw": None,
                "transaction_reference_number": ref,
            }

        # AQATO
        if "aqato" in flat_lower or "attc" in flat_lower:
            ref = self._aqato_ref()
            name = self._aqato_name()
            deadline = re.search(r"within\s+(\d+)\s+days?", self.full_text, re.IGNORECASE)
            return {
                "document_type": "skills_request_info",
                "authority": "AQATO",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "information_request": self._extract_message_content(self.text)[:1500],
                "deadline_raw": deadline.group(1) if deadline else None,
                "transaction_reference_number": ref,
            }

        # CA ANZ — deadline is phrased as a hold-duration ("3 months"), not
        # a calendar date, so deadline_raw is deliberately left unset rather
        # than mis-parsed.
        if "ca anz" in flat_lower or "afa-" in flat_lower:
            ref_match = re.search(r"\bAFA-\d{6}\b", self.full_text)
            ref = ref_match.group(0) if ref_match else None
            return {
                "document_type": "skills_request_info",
                "authority": "CA ANZ",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "information_request": self._extract_message_content(self.text)[:1500],
                "deadline_raw": None,
                "transaction_reference_number": ref,
            }

        # VETASSESS / EA / TRA (original Phase 4a logic, unchanged)
        ref = self._find_ref()

        if not ref:
            app_id = re.search(r"Application(?:\s*ID)?[:\s]*(\d+)", self.full_text)
            ref = app_id.group(1) if app_id else None

        name = self._applicants_name() or None
        if not name:
            name = self._dear_name()

        deadline = re.search(r"by\s+(\d{1,2}\s+\w+\s+\d{4})", self.full_text)
        if not deadline:
            deadline = re.search(r"within\s+(\d+)\s+calendar days", self.full_text)

        authority = "VETASSESS" if "vetassess" in flat_lower else (
            "EA" if "engineers australia" in flat_lower else "TRA"
        )

        return {
            "document_type": "skills_request_info",
            "authority": authority,
            "partner_application_id": ref,
            "name": name,
            "primary_applicant": {"name": name, "dob": None},
            "secondary_applicants": [],
            "information_request": self._extract_message_content(self.text)[:1500],
            "deadline_raw": deadline.group(1) if deadline else None,
            "transaction_reference_number": ref,
        }

    # ==============================================================
    # Generic notification bucket
    # ==============================================================

    def extract_skills_notification(self):

        flat_lower = self.full_text.lower()

        # ACECQA
        if "acecqa" in flat_lower:
            ref_match = re.search(r"[Cc]ase number:?\s*(\d+)", self.full_text)
            ref = str(int(ref_match.group(1))) if ref_match else None
            return {
                "document_type": "skills_notification",
                "authority": "ACECQA",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "notification_text": self._extract_message_content(self.text)[:500],
                "transaction_reference_number": ref,
            }

        # ACS
        if "acs" in flat_lower and ("acs.org.au" in flat_lower or self._acs_ref()):
            ref = self._acs_ref()
            return {
                "document_type": "skills_notification",
                "authority": "ACS",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "notification_text": self._extract_message_content(self.text)[:500],
                "transaction_reference_number": ref,
            }

        # AITSL
        if "aitsl" in flat_lower:
            ref_match = re.search(r"\bSAMS\d{9,10}\b", self.full_text) or \
                re.search(r"reference number:\s*([0-9a-fA-F]{8})", self.full_text, re.IGNORECASE)
            ref = ref_match.group(0) if ref_match else None
            return {
                "document_type": "skills_notification",
                "authority": "AITSL",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "notification_text": self._extract_message_content(self.text)[:500],
                "transaction_reference_number": ref,
            }

        # ANMAC
        if "anmac" in flat_lower:
            ref_match = re.search(r"\b(\d{6})\b", self.subject)
            ref = ref_match.group(1) if ref_match else None
            return {
                "document_type": "skills_notification",
                "authority": "ANMAC",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "notification_text": self._extract_message_content(self.text)[:500],
                "transaction_reference_number": ref,
            }

        # AQATO
        if "aqato" in flat_lower or "attc" in flat_lower:
            ref = self._aqato_ref()
            name = self._aqato_name()
            return {
                "document_type": "skills_notification",
                "authority": "AQATO",
                "partner_application_id": ref,
                "name": name,
                "primary_applicant": {"name": name, "dob": None},
                "secondary_applicants": [],
                "notification_text": self._extract_message_content(self.text)[:500],
                "transaction_reference_number": ref,
            }

        # CA ANZ
        if "ca anz" in flat_lower or "chartered accountants" in flat_lower or "afa-" in flat_lower:
            ref_match = re.search(r"\bAFA-\d{6}\b", self.full_text)
            ref = ref_match.group(0) if ref_match else None
            return {
                "document_type": "skills_notification",
                "authority": "CA ANZ",
                "partner_application_id": ref,
                "name": None,
                "primary_applicant": {"name": None, "dob": None},
                "secondary_applicants": [],
                "notification_text": self._extract_message_content(self.text)[:500],
                "transaction_reference_number": ref,
            }

        # VETASSESS / EA (original Phase 4a logic, unchanged)
        ref = self._find_ref()
        if not ref:
            app_id = re.search(r"Application(?:\s*ID)?[:\s]*(\d+)", self.full_text)
            ref = app_id.group(1) if app_id else None
            ea_id_m = re.search(r"EA ID\s*:?\s*(\d+)", self.full_text)
        else:
            ea_id_m = None

        name = self._applicants_name()
        if not name:
            m = re.search(r"(?:requested for|on behalf of)\s+(.+?)\s+is\s+\d+|(?:requested for|on behalf of)\s+(.+?)[.\n]", self.full_text)
            if m:
                name = self._clean(m.group(1) or m.group(2))

        # A real TRA "Payment Receipt" notification (from ssc.gov.au, no
        # "vetassess" anywhere in it) was found live falling all the way
        # through to this fallback and getting mislabeled "EA" — the only
        # two options this used to consider. Checked for explicitly now,
        # ahead of the "EA" default.
        #
        # TRA is checked FIRST, ahead of "vetassess" — a real TRA OSAP
        # payment receipt (PURVANG JITENDRABHAI PATEL, TRA26/777586851, from
        # TRA-Notifications@ssc.gov.au) includes an "RTO (if applicable):
        # VETASSESS" field naming the assessing body for that pathway, which
        # got the whole email mislabeled authority "VETASSESS" when that
        # substring check ran first. A genuine TRA reference/sender is
        # stronger evidence than an incidental "vetassess" mention.
        #
        # _find_ref() intentionally matches BOTH TRA's "TRA26/123456" shape
        # and VETASSESS's own "26AB123456" shape (see its docstring) — only
        # the TRA-shaped form counts as a TRA signal here, otherwise a
        # genuine VETASSESS reference would wrongly force authority "TRA".
        ref_for_authority = self._find_ref()
        looks_like_tra_ref = bool(ref_for_authority and re.match(r"^TRA\d{2}/", ref_for_authority))
        if looks_like_tra_ref or "ssc.gov.au" in flat_lower or "trades recognition australia" in flat_lower:
            authority = "TRA"
        elif "vetassess" in flat_lower:
            authority = "VETASSESS"
        else:
            authority = "EA"

        # Freeform text staff will see — trimmed body, not the full email.
        notification_text = self._extract_message_content(self.text)[:500]

        return {
            "document_type": "skills_notification",
            "authority": authority,
            "partner_application_id": ref,
            "ea_id": ea_id_m.group(1) if ea_id_m else None,
            "name": name,
            "primary_applicant": {"name": name, "dob": None},
            "secondary_applicants": [],
            "notification_text": notification_text,
            "applicant_email": self._applicant_email(),
            "transaction_reference_number": ref,
        }

    # ==============================================================
    # TRA JRP lifecycle — one generic bucket, real heading kept verbatim
    # ==============================================================

    def extract_skills_jrp_notification(self):

        ref = self._find_ref()
        name_match = re.search(r"TRA\d{2}/\d{6,10}\s*-\s*(.+)", self.subject)
        name = self._clean(name_match.group(1)) if name_match else None

        return {
            "document_type": "skills_jrp_notification",
            "authority": "TRA",
            "partner_application_id": ref,
            "name": name,
            "primary_applicant": {"name": name, "dob": None},
            "secondary_applicants": [],
            "notification_type": self._clean(self.subject) or self._clean(self.text[:300]),
            "transaction_reference_number": ref,
        }

    # ==============================================================
    # MASTER EXTRACTOR
    # ==============================================================

    def extract(self):
        doc_type = self.detect_document_type()

        if doc_type == "skills_lodgement":
            return self.extract_skills_lodgement()

        if doc_type == "skills_outcome":
            return self.extract_skills_outcome()

        if doc_type == "skills_request_info":
            return self.extract_skills_request_info()

        if doc_type == "skills_notification":
            return self.extract_skills_notification()

        if doc_type == "skills_jrp_notification":
            return self.extract_skills_jrp_notification()

        return {"document_type": "unknown"}
