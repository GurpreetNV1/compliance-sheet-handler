import os
from typing import List, Dict

from attachment_reader.pdf_parser.reader import extract_pdf_text
from attachment_reader.pdf_parser.extractor import IMMIExtractor
from attachment_reader.pdf_parser.skills_extractor import SkillsExtractor
from attachment_reader.pdf_parser.logger import (
    create_raw_log,
    create_extracted_log
)


class AttachmentProcessor:

    def __init__(self):
        pass

    def process_folder(self, attachment_dir: str, subject: str = None) -> List[Dict]:
        """
        Process all PDFs inside a folder and return extracted data.
        """

        if not os.path.exists(attachment_dir):
            print(f"Attachment folder not found: {attachment_dir}")
            return []

        pdf_files = [
            f for f in os.listdir(attachment_dir)
            if f.lower().endswith(".pdf")
        ]

        results = []

        for pdf_file in pdf_files:

            pdf_path = os.path.join(attachment_dir, pdf_file)

            print(f"\nProcessing PDF: {pdf_file}")

            try:
                # Step 1 — Extract raw text
                content = extract_pdf_text(pdf_path)

                # Step 2 — Log raw text
                raw_log_path = create_raw_log(content, pdf_file)

                # Step 3 — Structured extraction (IMMIExtractor first; fall
                # back to the Skills Assessment extractor — different
                # case-ID scheme/institution set entirely — if IMMIExtractor
                # doesn't recognize it)
                extracted_data = IMMIExtractor(content).extract()
                if extracted_data.get("document_type") == "unknown":
                    extracted_data = SkillsExtractor(content, subject=subject, filename=pdf_file).extract()

                # Step 4 — Log structured data
                extracted_log_path = create_extracted_log(
                    extracted_data,
                    pdf_file
                )

                extracted_data["source_file"] = pdf_file
                extracted_data["raw_log"] = raw_log_path
                extracted_data["extracted_log"] = extracted_log_path

                results.append(extracted_data)

                print("Extracted:", extracted_data.get("document_type"))

            except Exception as e:
                print(f"Failed processing {pdf_file}: {e}")

        return results

    def process_email_body(self, body_text, subject: str = None):
        """
        Some correspondence (e.g. ART's "documents received" confirmation,
        several VETASSESS/EA Skills Assessment notifications) has no PDF
        attachment at all — everything needed lives only in the email body.
        Tries IMMIExtractor first, then the Skills Assessment extractor;
        returns None if neither recognizes anything (rather than a doc with
        "unknown" type).
        """

        if not body_text or not body_text.strip():
            return None

        try:
            extracted_data = IMMIExtractor(body_text).extract()

            if extracted_data.get("document_type") == "unknown":
                extracted_data = SkillsExtractor(body_text, subject=subject).extract()

            if extracted_data.get("document_type") == "unknown":
                return None

            extracted_data["source_file"] = "email_body"

            print("Extracted (email body):", extracted_data.get("document_type"))

            return extracted_data

        except Exception as e:
            print(f"Failed processing email body: {e}")
            return None