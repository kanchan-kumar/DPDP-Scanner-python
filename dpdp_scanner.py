import os
import re
import json
import argparse
from datetime import datetime

from PIL import Image
import pytesseract
import PyPDF2
import docx

# -----------------------------
# DPDP REGEX PATTERNS
# -----------------------------
PATTERNS = {
    "AADHAAR": r"\b[2-9]{1}[0-9]{11}\b",
    "PAN": r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b",
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "PHONE": r"\b(\+91[- ]?)?[6-9][0-9]{9}\b",
    "IFSC": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    "UPI": r"\b[a-zA-Z0-9.\-_]{2,}@[a-zA-Z]{2,}\b",
    "PASSPORT": r"\b[A-Z]{1}[0-9]{7}\b"
}

SENSITIVE_KEYWORDS = [
    "caste", "religion", "health", "medical", "biometric",
    "sexual", "minor", "child", "dob", "date of birth"
]

# -----------------------------
# TEXT EXTRACTORS
# -----------------------------
def extract_text_from_pdf(path):
    text = ""
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""
    return text

def extract_text_from_docx(path):
    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs)

def extract_text_from_image(path):
    return pytesseract.image_to_string(Image.open(path))

def extract_text_from_binary(path):
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""

# -----------------------------
# CLASSIFICATION
# -----------------------------
def classify(identifier):
    if identifier in ["AADHAAR", "PAN", "PASSPORT"]:
        return "SENSITIVE_PERSONAL"
    if identifier in ["EMAIL", "PHONE", "UPI"]:
        return "PERSONAL"
    return "PERSONAL"

# -----------------------------
# SCAN TEXT
# -----------------------------
def scan_text(text, file_path):
    findings = []

    for id_type, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text):
            confidence = 0.9

            context_window = text[max(0, match.start()-50): match.end()+50].lower()
            if any(k in context_window for k in SENSITIVE_KEYWORDS):
                confidence += 0.05

            findings.append({
                "identifier_type": id_type,
                "category": classify(id_type),
                "value": match.group(),
                "confidence": round(min(confidence, 0.99), 2),
                "location": file_path
            })

    return findings

# -----------------------------
# FILE SCANNER
# -----------------------------
def scan_file(path):
    ext = path.lower().split(".")[-1]

    try:
        if ext == "pdf":
            text = extract_text_from_pdf(path)
        elif ext == "docx":
            text = extract_text_from_docx(path)
        elif ext in ["png", "jpg", "jpeg"]:
            text = extract_text_from_image(path)
        elif ext in ["txt", "csv", "json"]:
            with open(path, "r", errors="ignore") as f:
                text = f.read()
        else:
            text = extract_text_from_binary(path)

        return scan_text(text, path)

    except Exception:
        return []

# -----------------------------
# DIRECTORY SCAN
# -----------------------------
def scan_path(root):
    all_findings = []

    for dirpath, _, filenames in os.walk(root):
        for file in filenames:
            full_path = os.path.join(dirpath, file)
            all_findings.extend(scan_file(full_path))

    return all_findings

# -----------------------------
# MAIN
# -----------------------------
def main():
    parser = argparse.ArgumentParser(description="DPDP Data Scanner")
    parser.add_argument("path", nargs="?", default=".", help="Path to scan")
    args = parser.parse_args()

    print(f"🔍 Scanning path: {args.path}")
    findings = scan_path(args.path)

    output = {
        "scan_time": datetime.utcnow().isoformat(),
        "scan_root": os.path.abspath(args.path),
        "total_findings": len(findings),
        "findings": findings
    }

    with open("dpdp_scan_report.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Scan completed. Findings: {len(findings)}")
    print("📄 Output: dpdp_scan_report.json")

if __name__ == "__main__":
    main()

