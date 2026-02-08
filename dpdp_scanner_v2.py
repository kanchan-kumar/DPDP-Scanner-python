import os
import re
import json
import argparse
import hashlib
import socket
from datetime import datetime

from PIL import Image
import pytesseract
import PyPDF2
import docx

# =============================
# CONFIGURATION
# =============================
MAX_FILE_SIZE_MB = 20
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}
SUPPORTED_IMAGES = {"png", "jpg", "jpeg"}

# =============================
# DPDP REGEX PATTERNS
# =============================
PATTERNS = {
    "PAN": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "PHONE": r"\b(\+91[- ]?)?[6-9][0-9]{9}\b",
    "IFSC": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    "UPI": r"\b[a-zA-Z0-9.\-_]{2,}@(upi|ybl|okhdfcbank|oksbi|okaxis)\b",
    "PASSPORT": r"\b[A-Z][0-9]{7}\b"
}

AADHAAR_REGEX = r"\b[2-9][0-9]{11}\b"

SENSITIVE_CONTEXT = {
    "dob", "date of birth", "aadhaar", "pan", "account",
    "health", "medical", "caste", "religion", "minor", "child"
}

# Additional sensitive detection
BANK_ACCOUNT_REGEX = r"\b[0-9]{9,18}\b"
BANK_NAMES = [
    "State Bank of India", "SBI", "HDFC Bank", "ICICI Bank",
    "Axis Bank", "Kotak Mahindra Bank", "Punjab National Bank",
    "Bank of Baroda", "Canara Bank", "Union Bank of India"
]
ADDRESS_KEYWORDS = [
    "street", "road", "lane", "building", "apartment",
    "city", "district", "pincode", "state", "village"
]
NAME_REGEX = r"\b[A-Z][a-z]{2,}\s[A-Z][a-z]{2,}\b"  # e.g., John Doe

# =============================
# AADHAAR VERHOEFF CHECK
# =============================
def validate_aadhaar(num):
    mul = [[0,1,2,3,4,5,6,7,8,9],
           [1,2,3,4,0,6,7,8,9,5],
           [2,3,4,0,1,7,8,9,5,6],
           [3,4,0,1,2,8,9,5,6,7],
           [4,0,1,2,3,9,5,6,7,8],
           [5,9,8,7,6,0,4,3,2,1],
           [6,5,9,8,7,1,0,4,3,2],
           [7,6,5,9,8,2,1,0,4,3],
           [8,7,6,5,9,3,2,1,0,4],
           [9,8,7,6,5,4,3,2,1,0]]
    perm = [[0,1,2,3,4,5,6,7,8,9],
            [1,5,7,6,2,8,3,0,9,4],
            [5,8,0,3,7,9,6,1,4,2],
            [8,9,1,6,0,4,3,5,2,7],
            [9,4,5,3,1,2,6,8,7,0],
            [4,2,8,6,5,7,3,9,0,1],
            [2,7,9,3,8,0,6,4,1,5],
            [7,0,4,6,9,1,3,2,5,8]]

    c = 0
    for i, item in enumerate(reversed(num)):
        c = mul[c][perm[i % 8][int(item)]]
    return c == 0

# =============================
# UTILITIES
# =============================
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def is_large_file(path):
    return os.path.getsize(path) > MAX_FILE_SIZE_MB * 1024 * 1024

# =============================
# TEXT EXTRACTION
# =============================
def extract_text(path):
    ext = path.lower().split(".")[-1]

    if ext == "pdf":
        text = ""
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages[:20]:  # limit pages for performance
                text += page.extract_text() or ""
        return text

    if ext == "docx":
        doc = docx.Document(path)
        return "\n".join(p.text for p in doc.paragraphs)

    if ext in SUPPORTED_IMAGES:
        return pytesseract.image_to_string(Image.open(path))

    try:
        with open(path, "r", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

# =============================
# CLASSIFICATION
# =============================
def category(id_type):
    if id_type in {"AADHAAR", "PAN", "PASSPORT", "BANK_ACCOUNT"}:
        return "SENSITIVE_PERSONAL"
    if id_type in {"NAME", "ADDRESS", "BANK_NAME"}:
        return "PERSONAL"
    return "PERSONAL"

# =============================
# BUILD FINDING
# =============================
def build_finding(id_type, value, path, file_hash, confidence):
    return {
        "identifier_type": id_type,
        "category": category(id_type),
        "value": value,
        "confidence": round(confidence, 2),
        "file_path": path,
        "file_hash": file_hash
    }

# =============================
# ADDITIONAL SCANNING
# =============================
def scan_additional(text, path, file_hash):
    findings = []

    # Bank Accounts
    for m in re.finditer(BANK_ACCOUNT_REGEX, text):
        val = m.group()
        if 9 <= len(val) <= 18 and not val.startswith(("6","7","8","9")):
            findings.append(build_finding("BANK_ACCOUNT", val, path, file_hash, 0.9))

    # Bank Names
    for bank in BANK_NAMES:
        for m in re.finditer(re.escape(bank), text, re.IGNORECASE):
            val = m.group()
            findings.append(build_finding("BANK_NAME", val, path, file_hash, 0.95))

    # Names
    # for m in re.finditer(NAME_REGEX, text):
    #     val = m.group()
    #     if val not in BANK_NAMES:
    #         findings.append(build_finding("NAME", val, path, file_hash, 0.85))

    # Addresses (heuristic)
    # for line in text.splitlines():
    #     if any(k in line.lower() for k in ADDRESS_KEYWORDS):
    #         val = line.strip()
    #         if 10 < len(val) < 200:
    #             findings.append(build_finding("ADDRESS", val, path, file_hash, 0.8))

    return findings

# =============================
# CORE SCAN TEXT
# =============================
def scan_text(text, path, file_hash):
    findings = []
    seen = set()

    # Aadhaar
    for m in re.finditer(AADHAAR_REGEX, text):
        val = m.group()
        if validate_aadhaar(val):
            seen.add((val, "AADHAAR"))
            findings.append(build_finding("AADHAAR", val, path, file_hash, 0.98))

    # Other DPDP identifiers
    for id_type, regex in PATTERNS.items():
        for m in re.finditer(regex, text):
            val = m.group()
            key = (val, id_type)
            if key in seen:
                continue
            context = text[max(0, m.start()-60):m.end()+60].lower()
            confidence = 0.9 + (0.05 if any(k in context for k in SENSITIVE_CONTEXT) else 0)
            findings.append(build_finding(id_type, val, path, file_hash, min(confidence, 0.99)))
            seen.add(key)

    # Additional types: Name, Address, Bank Account/Name
    findings.extend(scan_additional(text, path, file_hash))

    return findings

# =============================
# DIRECTORY SCAN
# =============================
def scan(root):
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for file in filenames:
            full_path = os.path.join(dirpath, file)
            try:
                if is_large_file(full_path):
                    continue
                file_hash = sha256(full_path)
                text = extract_text(full_path)
                results.extend(scan_text(text, full_path, file_hash))
            except Exception:
                continue
    return results

# =============================
# MAIN
# =============================
def main():
    parser = argparse.ArgumentParser(description="DPDP Data Scanner v3")
    parser.add_argument("path", nargs="?", default=".", help="Path to scan")
    args = parser.parse_args()

    start_time = datetime.utcnow()
    findings = scan(args.path)
    end_time = datetime.utcnow()

    output = {
        "scanner_version": "3.0",
        "scan_root": os.path.abspath(args.path),
        "host": socket.gethostname(),
        "started_at": start_time.isoformat(),
        "ended_at": end_time.isoformat(),
        "total_findings": len(findings),
        "findings": findings
    }

    with open("dpdp_scan_report.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"✅ Scan completed | Total Findings: {len(findings)}")
    print("📄 Output file: dpdp_scan_report.json")

if __name__ == "__main__":
    main()
