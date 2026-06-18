from core.business_rules import BusinessRulesEngine

engine = BusinessRulesEngine()

sample_docs = [
    {
        "document_type": "grant",
        "primary_applicant": {"name": "John"},
        "visa_program": "Student Visa",
        "transaction_reference_number": "TRN1"
    },
    {
        "document_type": "grant",
        "primary_applicant": {"name": "Jane"},
        "visa_program": "Student Visa",
        "transaction_reference_number": "TRN2"
    }
]

entries = engine.decide_entries(sample_docs)

print(entries)