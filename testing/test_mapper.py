from core.field_mapper import FieldMapper

mapper = FieldMapper()

payload = {
    "document_type": "acknowledgement",
    "document": {
        "primary_applicant": {"name": "John Doe"},
        "visa_program": "Student Visa",
        "date": "2026-01-01",
        "transaction_reference_number": "TRN123"
    }
}

agentcis = {
    "clientName": "Johnathan Doe",
    "internalId": "12345",
    "applicationId": "APP001",
    "assignee": "Consultant A"
}

email_meta = {
    "date": "2026-01-02"
}

print(mapper.map_to_sheet(payload, agentcis, email_meta))