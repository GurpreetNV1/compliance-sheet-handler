import os

from dotenv import load_dotenv

load_dotenv()

GOOGLE_APPS_SCRIPT_SECRET = os.getenv("GOOGLE_APPS_SCRIPT_SECRET")

VISA_API_URL = os.getenv("VISA_API_URL")
STUDENT_VISA_API_URL = os.getenv("STUDENT_VISA_API_URL")
RFI_API_URL = os.getenv("RFI_API_URL")
ART_API_URL = os.getenv("ART_API_URL")
SKILLS_API_URL = os.getenv("SKILLS_API_URL")

# Phase-1 scope: acknowledgement -> Lodgement, grant/refusal/nomination/sponsorship
# -> Outcomes, bridging_visa -> the visa-type-specific bridging tab, s56 -> the
# visa-type-specific RFMI tab.
# Phase-2a scope (added): health_examination, s57, s64, citizenship_appointment,
# and the generic "notification" bucket (refund/withdrawal/assessment-commence/
# citizenship-approval/general).
# Phase-3 scope (added): ART (Administrative Review Tribunal) — one shared
# spreadsheet regardless of mailbox, so its routing doesn't go through
# MAILBOX_ROUTES at all, just a flat doc_type -> tab map below.
# Phase-4a scope (added): Skills Assessment (VETASSESS/EA/TRA) — same
# mailbox-independent pattern as ART. Correspondence arrives at skills@
# (VETASSESS/EA) and visa@ (TRA); skills@ is deliberately NOT a
# MAILBOX_ROUTES key (it has no IMMI-style tabs of its own), so this routing
# must be checked before the MAILBOX_ROUTES lookup below, not after.
# Remaining 6 authorities (ACECQA/ACS/AIMS/ANMAC/AQATO/CA ANZ) are a
# fast-follow.

MAILBOX_ROUTES = {
    "visa@acmemigration.com": {
        "spreadsheet_url": VISA_API_URL,
        "tabs": {
            "acknowledgement": "Lodgement",
            "grant": "Outcomes",
            "refusal": "Outcomes",
            "withdrawal": "Outcomes",
            "nomination": "Outcomes",
            "sponsorship": "Outcomes",
            "bridging_visa": "Subsequent Bridging Visa",
            "health_examination": "Subsequent Health Examinations",
            "citizenship_appointment": "Citizenship Appointment Letter",
        },
        "s56_tab": "S56 Visa",
        "s57_tab": "S57 Visa",
    },
    "study@acmemigration.com": {
        "spreadsheet_url": STUDENT_VISA_API_URL,
        "tabs": {
            "acknowledgement": "Lodgement",
            "grant": "Outcomes",
            "refusal": "Outcomes",
            "withdrawal": "Outcomes",
            "nomination": "Outcomes",
            "sponsorship": "Outcomes",
            "bridging_visa": "Bridging Visa",
            "health_examination": "Health Examinations",
        },
        "s56_tab": "S56 Student",
        "s57_tab": "S57 Student",
    },
    # No IMMI-style tabs of its own — present only so Orchestrator's mailbox
    # loop (which iterates MAILBOX_ROUTES keys) actually fetches from this
    # mailbox at all. VETASSESS/EA doc types route entirely via SKILLS_TABS
    # above, checked before this dict is ever consulted.
    "skills@acmemigration.com": {
        "spreadsheet_url": None,
        "tabs": {},
        "s56_tab": None,
        "s57_tab": None,
    },
}

# S64 only has one tab in RFMI (no student variant) regardless of source mailbox.
S64_TAB = "S64 Visa"

# ART has one spreadsheet regardless of source mailbox (visa@/study@ both
# feed the same tabs) — both Lodgement stages write/upsert into "Lodgement".
ART_TABS = {
    "art_lodgement_stage1": "Lodgement",
    "art_lodgement_stage2": "Lodgement",
    "art_outcome": "Outcomes",
    "art_notice_of_hearing": "Notice of Hearing",
    "art_notification": "Notifications",
}

# Skills Assessment has one spreadsheet regardless of source mailbox
# (skills@ for VETASSESS/EA, visa@ for TRA). Approvals Expiry is filled in
# manually by staff, never written by the pipeline — no tab needed here.
SKILLS_TABS = {
    "skills_lodgement": "Lodgement",
    "skills_outcome": "Outcomes",
    "skills_request_info": "Request For More Information",
    "skills_notification": "Notifications",
    "skills_jrp_notification": "JRP",
}


def _resolve_notification_tab(mailbox: str, document: dict):
    """
    Visa mailbox has 3 notification-style tabs to choose between; Study only
    has one (S128). Routing is based on notification_subtype first, then
    visa_program keyword, falling back to the general bucket.
    """

    if mailbox == "study@acmemigration.com":
        return "S128 Notification of Decisions"

    subtype = document.get("notification_subtype")

    if subtype == "assessment_commence":
        return "Assessment Commence Notification"

    visa_program = (document.get("visa_program") or "").lower()
    if "partner" in visa_program:
        return "Partner Visa Notifications"

    return "Notifications"


def resolve_write_target(mailbox: str, doc_type: str, document: dict = None):
    """
    Given the mailbox an email was fetched from, the document type decided by
    BusinessRulesEngine, and (for "notification") the raw extracted document,
    return (spreadsheet_url, tab_name) to write to, or (None, None) if this
    doc_type isn't in scope for this mailbox.
    """

    # ART and Skills Assessment are mailbox-independent (one shared
    # spreadsheet each) — checked before the MAILBOX_ROUTES lookup below,
    # since skills@acmemigration.com isn't a MAILBOX_ROUTES key at all (it
    # has no IMMI-style tabs of its own) and would otherwise short-circuit
    # to (None, None) before ever reaching these.
    if doc_type in ART_TABS:
        return ART_API_URL, ART_TABS[doc_type]

    if doc_type in SKILLS_TABS:
        return SKILLS_API_URL, SKILLS_TABS[doc_type]

    route = MAILBOX_ROUTES.get(mailbox)
    if not route:
        return None, None

    if doc_type == "s56":
        return RFI_API_URL, route["s56_tab"]

    if doc_type == "s57":
        return RFI_API_URL, route["s57_tab"]

    if doc_type == "s64":
        return RFI_API_URL, S64_TAB

    if doc_type == "notification":
        return route["spreadsheet_url"], _resolve_notification_tab(mailbox, document or {})

    tab_name = route["tabs"].get(doc_type)
    if not tab_name:
        return None, None

    return route["spreadsheet_url"], tab_name
