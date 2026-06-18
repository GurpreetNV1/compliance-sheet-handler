import os
from typing import List, Dict

from attachment_reader.pdf_parser.reader import extract_pdf_text
from attachment_reader.pdf_parser.extractor import IMMIExtractor
from attachment_reader.pdf_parser.logger import (
    create_raw_log,
    create_extracted_log
)


class AttachmentProcessor:

    def __init__(self):
        pass

    def process_folder(self, attachment_dir: str) -> List[Dict]:
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

            print(f"\n📄 Processing PDF: {pdf_file}")

            try:
                # Step 1 — Extract raw text
                content = extract_pdf_text(pdf_path)

                # Step 2 — Log raw text
                raw_log_path = create_raw_log(content, pdf_file)

                # Step 3 — Structured extraction
                extractor = IMMIExtractor(content)
                extracted_data = extractor.extract()

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