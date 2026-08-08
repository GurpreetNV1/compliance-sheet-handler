import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from attachment_reader.pdf_parser.extractor import IMMIExtractor
from core.field_mapper import FieldMapper
from sheets.visa_lookup import find_client_by_trn


NOMINATION_WITHDRAWAL_TEXT = """
Skilled Visa Processing Centre
Department of Home Affairs
WEBSITE: www.homeaffairs.gov.au
27 July 2026
MYRIAD TECHNOLOGIES PTY LTD
In reply quote:
Name of applicant MYRIAD TECHNOLOGIES PTY LTD
Application ID 770689719
Name of nominee Shruti AGARWAL
Nomination transaction reference number EGP36BJAIY
Visa program Employer Nomination Scheme (subclass 186)
visa
File number BCC2024/4789126
Transmission method Email sent to visa@acmemigration.com
Dear Applicant
Acknowledgement of withdrawal of a nomination application
Your nomination application for a ENS Nomination (Direct Entry) (subclass 186) visa was
withdrawn as requested.
It is not possible to reconsider an application after it has been withdrawn. If at any time in the future
you wish to apply for another application, a new application must be lodged.
MYRIAD TECHNOLOGIES PTY LTD
Nominee(s)
Shruti AGARWAL 28 October 1994
Position
Software Engineer - 261313
Application fee
The application fee which has already been paid was for the processing of the application and it
must be paid regardless of the application outcome.
Questions about the withdrawal of your application
If you have questions about the withdrawal of this application, you may contact us by any of the
means listed below.
The original of this letter including any attachments was sent to your authorised recipient:
Ravi Vipulbhai SHAH
visa@acmemigration.com
"""

NORMAL_WITHDRAWAL_TEXT = """
Skilled Visa Processing Centre
Department of Home Affairs
WEBSITE: www.homeaffairs.gov.au
27 July 2026
Shruti AGARWAL
UNIT 5,8 COOK ST
YERONGA QLD 4104
In reply quote:
Client name Shruti AGARWAL
Date of birth 28 October 1994
Date of visa application 06 September 2024
Application ID 1290691153
Transaction reference number EGP3VQ8KTU
File number BCC2024/4842601
Transmission method Email sent to VISA@ACMEMIGRATION.COM
Dear Shruti AGARWAL
Acknowledgement of withdrawal of an application for a Employer Nomination Scheme
(subclass 186) visa
Name Date of birth
Shruti AGARWAL 28 October 1994
Your application for a Employer Nomination Scheme (subclass 186) visa was withdrawn on 27 July
2026.
We cannot reconsider an application after it has been withdrawn.
If you want to apply for another visa, you will need to lodge a new application.
Your immigration status
You currently hold a Bridging B (subclass 020) visa that was granted in association with this visa
application, which will cease 35 calendar days from the date the application was withdrawn.
The original of this letter including any attachments was sent to your authorised recipient:
Ravi Vipulbhai SHAH
VISA@ACMEMIGRATION.COM
"""

NORMAL_REFUSAL_TEXT = """
Department of Home Affairs
WEBSITE: www.homeaffairs.gov.au
05 August 2026
Tejaswi Ninni YADLA
45-40-48, ABID NAGAR
AKKAYAPALEM VISAKHAPATNAM
URBAN ANDHRA PRADESH 530016
INDIA
In reply quote:
Client name Tejaswi Ninni YADLA
Date of birth 03 June 1993
Date of visa application 20 July 2026
Application ID 830723530
Transaction reference number EGPDFUWFG0
File number BCC2026/4016431
Visa application charge receipt number 9045975026
Transmission method Email sent to VISA@ACMEMIGRATION.COM
Dear Tejaswi Ninni YADLA
Notification of refusal of application for a Visitor (class FA) Visitor (Sponsored Family)
(subclass 600) visa
Refused applicant
I wish to advise you that the application for this visa has been refused on 05 August 2026 for the
following applicant:
Client name Tejaswi Ninni YADLA
Date of birth 03 June 1993
The applicant did not satisfy the provisions of the Migration Regulations 1994.
The attached decision record provides detailed information about this decision as it applies to this
applicant.
DECISION RECORD
Application details
Visa class Visitor (class FA) Visitor (Sponsored Family)
(subclass 600)
Stream (main applicant only) Sponsored Family
Date of visa application 20 July 2026
Transaction reference number EGPDFUWFG0
Application ID 830723530
File number BCC2026/4016431
Visa application charge receipt number 9045975026
Client name Tejaswi Ninni YADLA
Date of birth 03 June 1993
Client ID 11887016251
Visa subclass stream Sponsored Family
The applicant's claims
The applicant has applied for the grant of a Visitor visa (subclass 600) to visit Australia for a
temporary stay.
Decision
As clause 600.211 is not satisfied, I find the criteria for the grant of a Visitor (Sponsored Family)
visa in the Sponsored Family stream are not satisfied. Therefore, I refuse the application by the
applicant for a Visitor (Sponsored Family) visa in the Sponsored Family stream.
The original of this letter including any attachments was sent to your authorised recipient:
Ravi Vipulbhai SHAH
VISA@ACMEMIGRATION.COM
"""

NOMINATION_REFUSAL_TEXT = """
Department of Home Affairs
CONTACT VIA: immi.homeaffairs.gov.au/help-support/applying-online-or-on-paper/online WEBSITE: www.homeaffairs.gov.au
08 August 2026
POROUS LANE PTY LTD
Unit 7, 81 Cooper Street,
CAMPBELLFIELD VIC 3061
In reply quote:
Name of applicant POROUS LANE PTY LTD
Application ID 895708462
Name of nominee Aishwarya Kiran PAWAR
Nomination transaction reference number EGP96DYFQ3
File number BCC2025/5281712
Transmission method Email sent to VISA@ACMEMIGRATION.COM
Dear Applicant
Notification of refusal of a nomination application
Nominee
Aishwarya Kiran PAWAR 21 November 1995
I wish to advise that the application for approval of a nomination has been refused. The attached
nomination refusal decision record outlines details about this decision.
NOTICE OF DECISION
NOMINATION REFUSAL NOTICE
TRAINING(NOMINATION) SUBCLASS 407 VISA
Details of Nomination
Name of sponsor POROUS LANE PTY LTD
Sponsorship application ID 1940707879
Nominated person
Client name Aishwarya Kiran PAWAR
Client ID 21500564976
Date of birth 21 November 1995
Passport number S4280988
Proposed occupation, training or activity Program or Project Administrator - 511112
Therefore, I refuse POROUS LANE PTY LTD's application for approval of a nomination.
Delegate of the Minister
Position Number: 60171551
Department of Home Affairs
08 August 2026
"""


SAMPLES = [
    ("Nomination Withdrawal", NOMINATION_WITHDRAWAL_TEXT, "extract_nomination_withdrawal"),
    ("Normal Withdrawal", NORMAL_WITHDRAWAL_TEXT, "extract_withdrawal"),
    ("Normal Refusal", NORMAL_REFUSAL_TEXT, "extract_refusal"),
    ("Nomination Refusal", NOMINATION_REFUSAL_TEXT, "extract_nomination_refusal"),
]

mapper = FieldMapper()

for label, text, expected_method in SAMPLES:
    print("=" * 70)
    print(label)
    print("=" * 70)

    extractor = IMMIExtractor(text)
    doc_type = extractor.detect_document_type()
    print(f"detect_document_type() -> {doc_type!r}")

    method_name = f"extract_{doc_type}"
    if method_name != expected_method:
        print(f"  !! WARNING: expected {expected_method}, detector produced doc_type {doc_type!r}")

    doc = getattr(extractor, method_name)()
    print(f"{method_name}() ->")
    for key, value in doc.items():
        print(f"    {key}: {value!r}")

    trn = doc.get("transaction_reference_number")
    print(f"\nfind_client_by_trn({trn!r}) against the live Visa sheet...")
    try:
        trn_match = find_client_by_trn(trn)
        print(f"  -> {trn_match!r}")
    except Exception as e:
        print(f"  !! Lookup raised: {e}")
        trn_match = None

    agentcis_data = trn_match or {}

    payload = {"document_type": doc_type, "document": doc}
    email_meta = {
        "date": "Fri, 08 Aug 2026 10:00:00 +1000",
        "subject": f"Fwd: {label}",
        "cc": [],
        "recipients": ["visa@acmemigration.com"],
    }

    result = mapper.map_to_sheet(payload, agentcis_data, email_meta)
    print("\nmap_to_sheet() sheet_fields ->")
    for key, value in result.get("fields", {}).items():
        print(f"    {key!r}: {value!r}")

    print()
