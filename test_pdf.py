import pdfplumber
import sys
import io

# Force stdout to UTF-8 on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

with pdfplumber.open("resume.pdf") as pdf:
    text = ""
    for page in pdf.pages:
        t = page.extract_text()
        if t:
            text += t + "\n"

print(f"Pages: {len(pdf.pages)}")
print(f"Characters extracted: {len(text)}")
print("\n--- FIRST 1500 CHARS ---")
print(text[:1500])
print("--- END ---")

if len(text) < 100:
    print("\nWARNING: Very little text extracted - PDF may be image-based!")
