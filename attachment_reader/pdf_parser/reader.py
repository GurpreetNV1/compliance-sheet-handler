import pdfplumber

def extract_pdf_text(pdf_path: str) -> str:
    """
    Extracts all text from the given PDF file
    and logs page by page.
    """
    full_text = ""

    with pdfplumber.open(pdf_path) as pdf:
        full_text += f"Total Pages: {len(pdf.pages)}\n"
        full_text += "=" * 50 + "\n"

        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()

            full_text += f"\n\n----- Page {page_number} -----\n\n"
            full_text += text if text else "[No text found]"

    return full_text