"""
resume_parser.py
Phase 1: Extract text from PDF and parse into structured candidate profile using Groq LLM.
"""

import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pdfplumber
import json
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract raw text from a PDF file."""
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()


def parse_resume(pdf_path: str) -> dict:
    """Extract and parse resume into structured candidate profile JSON."""
    raw_text = extract_text_from_pdf(pdf_path)

    if not raw_text:
        raise ValueError("Could not extract text from PDF. Ensure the file is not corrupted or scanned image.")

    prompt = f"""
You are an expert technical resume parser and candidate profiler.
Extract factual structured information from the resume below.
DO NOT hallucinate or assume unlisted credentials. If information is missing, use null or [].

Determine candidate_level carefully:
- If currently pursuing a degree (e.g. graduation year in future or stated as student), set candidate_level="student", is_student=true, years_of_experience=0 (or total months of actual industry experience).
- If recently graduated with 0-1 years exp, candidate_level="entry-level", is_student=false.
- Otherwise candidate_level="experienced".

Return ONLY valid JSON with this exact schema — no markdown fences, no explanatory text:
{{
  "name": "string or null",
  "email": "string or null",
  "phone": "string or null",
  "candidate_level": "student | entry-level | experienced",
  "is_student": true | false,
  "years_of_experience": 0,
  "education": [
    {{
      "degree": "string",
      "field": "string",
      "institution": "string",
      "graduation_year": "string or null",
      "is_current": true | false
    }}
  ],
  "programming_languages": ["Python", "C++", ...],
  "frameworks": ["TensorFlow", "FastAPI", ...],
  "tools": ["Docker", "Git", ...],
  "skills": ["all technical, domain, and soft skills"],
  "projects": [
    {{
      "name": "string",
      "technologies": ["string"],
      "summary": "string"
    }}
  ],
  "experience": [
    {{
      "title": "string",
      "company": "string",
      "duration": "string",
      "summary": "string",
      "is_internship_or_club": true | false
    }}
  ],
  "keywords": ["top 15 distinct technical keywords and domains"]
}}

RESUME TEXT:
{raw_text[:6000]}
"""

    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    raw_json = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw_json.startswith("```"):
        raw_json = raw_json.split("```")[1]
        if raw_json.startswith("json"):
            raw_json = raw_json[4:]
    return json.loads(raw_json)


if __name__ == "__main__":
    from rich import print as rprint

    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "resume.pdf"
    rprint(f"[bold cyan]Parsing:[/bold cyan] {pdf_path}")
    result = parse_resume(pdf_path)
    rprint("[bold green]✓ Resume parsed successfully[/bold green]")
    rprint(result)
