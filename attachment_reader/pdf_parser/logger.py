import os
import json
from datetime import datetime


def create_raw_log(content: str, pdf_name: str) -> str:
    os.makedirs("logs/raw", exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pdf_base = os.path.splitext(pdf_name)[0]

    filename = f"{timestamp}__{pdf_base}.log"
    file_path = os.path.join("logs/raw", filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    return file_path


def create_extracted_log(data: dict, pdf_name: str) -> str:
    os.makedirs("logs/extracted", exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    pdf_base = os.path.splitext(pdf_name)[0]

    filename = f"{timestamp}__{pdf_base}.json"
    file_path = os.path.join("logs/extracted", filename)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

    return file_path