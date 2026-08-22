"""
ranker.py
Phase 2b: Description-driven hard filter + transparent dual-score ranking.

Score model:
  tech_score   (0-100): pure skill/project/education fit — honest about what it measures
  eligibility_status:   Eligible | Requires Verification | Ineligible
  eligibility_breakdown: per-factor verdict with ✓/⚠ prefix

Pipeline:
  1. check_hard_eligibility()   — Python regex, fast O(n) hard filter
  2. pre_screen_eligibility()   — Python rules, produces per-factor signals for LLM
  3. rank_jobs() via LLM        — LLM sees pre-screened signals and CANNOT override them
"""

import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import re
import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ── Hard Disqualifiers (title-level) ──────────────────────────────────────────

DISQUALIFYING_TITLES = [
    r"\bsenior\b", r"\bsr\.?\b", r"\blead\b", r"\bstaff\b", r"\bprincipal\b",
    r"\bdirector\b", r"\bhead\s+of\b", r"\bvp\b", r"\bvice\s+president\b",
    r"\bmanager\b", r"\barchitect\b", r"\bgestionnaire\b", r"\bsuperviseur\b",
    r"\bexecutive\b"
]

NON_TECH_TITLES = [
    r"\baccount\s+executive\b", r"\bproduct\s+sales\b", r"\bsales\s+development\b",
    r"\blegal\b", r"\bcounsel\b", r"\btax\b", r"\bpayroll\b", r"\bcompliance\b",
    r"\bunderwriting\b", r"\blending\b", r"\brecruiter\b", r"\brecruiting\b",
    r"\bmarketing\b", r"\bfinancial\s+analyst\b", r"\baccounting\b",
    # Non-engineering office/admin roles
    r"\badministrat\w+\b",        # administrative, administrator
    r"\bcoordinator\b",
    r"\bbusiness\s+partner\b",
    r"\bexecutive\s+assistant\b",
    r"\boffice\s+manager\b",
    r"\bfacilities\b",
    r"\breceptionist\b",
    r"\bcustomer\s+success\b",
    r"\bcustomer\s+support\b",
    r"\bcommunity\s+manager\b",
    r"\bcontent\s+writer\b",
    r"\bcopywriter\b",
    r"\bhr\s+\w+\b",              # HR Generalist, HR Partner etc.
    r"\bhuman\s+resources\b",
    r"\bpeople\s+op\w*\b",        # People Ops, People Operations
    r"\bpeople\s+partner\b",
    r"\btalent\s+\w+\b",          # Talent Acquisition, Talent Partner
]

STUDENT_FRIENDLY_TITLES = [
    r"\bintern\b", r"\binternship\b", r"\bco-?op\b", r"\bstudent\b",
    r"\bnew\s+grad\b", r"\bentry\s+level\b", r"\bjunior\b", r"\bassociate\b",
    r"\bapprentice\b", r"\bfellow\b", r"\bearly\s+career\b"
]

# ── Description patterns ───────────────────────────────────────────────────────

EXP_REQUIRED_RE = re.compile(
    r"([3-9]|1[0-9])\+?\s*(?:-\s*\d+)?\s*(?:years?|yrs?)"
    r"(?:\s+of)?\s+(?:experience|industry experience|relevant experience|professional experience|work experience)",
    re.IGNORECASE
)

HARD_LOCATION_SIGNALS_RE = re.compile(
    r"\b(china|beijing|shanghai|japan|tokyo|korea|seoul|germany|berlin|france|paris"
    r"|singapore|australia|sydney|brazil|mexico|taiwan|taipei)\b",
    re.IGNORECASE
)

REMOTE_POSITIVE_RE = re.compile(
    r"\b(remote|work from home|wfh|distributed|global|worldwide|anywhere)\b",
    re.IGNORECASE
)

VISA_SPONSORSHIP_RE = re.compile(
    r"\b(visa sponsorship|sponsorship available|will sponsor|open to international)\b",
    re.IGNORECASE
)

# Explicit US-only work authorization restriction
US_AUTH_REQUIRED_RE = re.compile(
    r"(must be (authorized|eligible) to work in the (united states|us|usa)"
    r"|authorized to work in the us"
    r"|us\s+work authorization required"
    r"|us\s+citizens? and (permanent residents?|green card))",
    re.IGNORECASE
)

# India-friendly signals
INDIA_FRIENDLY_RE = re.compile(
    r"\b(india|bangalore|bengaluru|hyderabad|pune|mumbai|delhi|chennai|kolkata)\b",
    re.IGNORECASE
)

ENTRY_LEVEL_RE = re.compile(
    r"\b(new\s+grad|entry.?level|no\s+experience\s+required|0.?1\s+years?|recent\s+graduate|fresh\s+graduate)\b",
    re.IGNORECASE
)


# ── Stage 1: Hard eligibility filter ─────────────────────────────────────────

def check_hard_eligibility(job: dict, candidate_profile: dict) -> tuple[bool, str]:
    """
    Returns (is_retained, rejection_reason).
    Inspects BOTH title AND description body.
    """
    title = (job.get("title") or "").strip()
    title_lower = title.lower()
    description = re.sub(r"<[^>]+>", " ", (job.get("content") or "")).lower()

    is_student = candidate_profile.get("is_student", True)
    years_exp = candidate_profile.get("years_of_experience", 0)
    is_student_level = is_student or years_exp <= 1

    # ── Title-based seniority / domain disqualifiers ──────────────────────────
    if is_student_level:
        is_intern_role = any(re.search(pat, title_lower) for pat in STUDENT_FRIENDLY_TITLES)

        if not is_intern_role:
            for pat in DISQUALIFYING_TITLES:
                if re.search(pat, title_lower):
                    return False, f"Seniority mismatch ('{title}')"
            for pat in NON_TECH_TITLES:
                if re.search(pat, title_lower):
                    return False, f"Non-tech domain ('{title}')"

    # ── Description-based experience requirement ──────────────────────────────
    if is_student_level:
        exp_matches = EXP_REQUIRED_RE.findall(description)
        if exp_matches:
            min_years = min(int(m) for m in exp_matches)
            if min_years >= 3:
                return False, f"Description requires {min_years}+ yrs experience"

    # ── Hard location disqualifier ────────────────────────────────────────────
    location_name = (job.get("location") or {})
    if isinstance(location_name, dict):
        location_name = location_name.get("name", "")
    location_str = (location_name or "").lower()

    if HARD_LOCATION_SIGNALS_RE.search(location_str):
        if not REMOTE_POSITIVE_RE.search(description) and not VISA_SPONSORSHIP_RE.search(description):
            return False, f"Non-remote international location: {location_str}"

    return True, "Passed"


def filter_eligible_jobs(jobs: list[dict], candidate_profile: dict) -> list[dict]:
    """Apply hard eligibility filter across all fetched jobs."""
    eligible = []
    for job in jobs:
        retained, reason = check_hard_eligibility(job, candidate_profile)
        if retained:
            job["_hard_filter_status"] = reason
            eligible.append(job)
    return eligible


# ── Stage 2: Python pre-screening (runs before LLM) ───────────────────────────

def pre_screen_eligibility(job: dict) -> tuple[str, list[str]]:
    """
    Python-rules eligibility pre-screening. Produces concrete signals for the LLM.
    Returns (pre_status, signals):
      pre_status: 'likely_eligible' | 'requires_verification' | 'likely_ineligible'
      signals: list of ✓/⚠ strings the LLM must incorporate
    """
    description = re.sub(r"<[^>]+>", " ", (job.get("content") or ""))
    desc_lower = description.lower()

    location = (job.get("location") or {})
    if isinstance(location, dict):
        location = location.get("name", "")
    location_lower = (location or "").lower()

    signals = []
    flags = []   # negative
    positives = []  # positive

    # Work authorization — hard wall
    if US_AUTH_REQUIRED_RE.search(desc_lower):
        flags.append("⚠ Work Authorization: US authorization explicitly required")

    # Location
    if INDIA_FRIENDLY_RE.search(desc_lower + location_lower):
        positives.append("✓ Location: India office or India-friendly role detected")
    if REMOTE_POSITIVE_RE.search(desc_lower):
        positives.append("✓ Location: Remote work explicitly mentioned")
    elif not INDIA_FRIENDLY_RE.search(location_lower):
        # Not remote, not India — uncertain
        flags.append(f"⚠ Location: On-site in '{location}' — remote eligibility unclear")

    # Entry-level signals
    if ENTRY_LEVEL_RE.search(desc_lower):
        positives.append("✓ Experience: Entry-level / new grad explicitly welcome")

    # Visa sponsorship
    if VISA_SPONSORSHIP_RE.search(desc_lower):
        positives.append("✓ Work Authorization: Visa sponsorship mentioned")

    signals = positives + flags

    # Determine pre_status
    has_hard_block = any("US authorization explicitly required" in s for s in flags)
    has_location_flag = any("remote eligibility unclear" in s for s in flags)

    if has_hard_block:
        pre_status = "likely_ineligible"
    elif flags:
        pre_status = "requires_verification"
    else:
        pre_status = "likely_eligible"

    # Add a summary signal if no signals at all
    if not signals:
        signals.append("⚠ Eligibility: No explicit remote/location/visa signals found — verification needed")
        pre_status = "requires_verification"

    return pre_status, signals


# ── Stage 3: LLM ranking with pre-screened context ────────────────────────────

def rank_jobs(resume: dict, jobs: list[dict], top_n: int = 3) -> list[dict]:
    """
    1. Hard-filter (Python regex).
    2. Pre-screen eligibility (Python rules) — injected into LLM context.
    3. LLM ranks Top N with dual score: tech_score + eligibility_status.
       LLM cannot override Python-determined 'likely_ineligible' signals.
    """
    eligible_jobs = filter_eligible_jobs(jobs, resume)
    pool = eligible_jobs if eligible_jobs else jobs[:15]

    # Build slim job objects with pre-screened eligibility signals
    slim_jobs = []
    for j in pool[:50]:
        content = j.get("content", "") or ""
        clean_content = re.sub(r"<[^>]+>", " ", content)[:1200]
        loc = j.get("location", {})
        if isinstance(loc, dict):
            loc = loc.get("name", "Remote / Unspecified")

        pre_status, pre_signals = pre_screen_eligibility(j)

        slim_jobs.append({
            "id": j.get("id"),
            "title": j.get("title"),
            "company": j.get("_company_slug", j.get("company", "")),
            "location": loc,
            "url": j.get("absolute_url",
                         f"https://job-boards.greenhouse.io/embed/job_app"
                         f"?for={j.get('_company_slug')}&token={j.get('id')}"),
            "description": clean_content.strip(),
            # Pre-computed eligibility — LLM must respect these
            "pre_eligibility_status": pre_status,
            "pre_eligibility_signals": pre_signals,
        })

    edu_str = json.dumps(resume.get("education", []))
    skills_str = ", ".join(resume.get("skills", [])[:18])
    projects_str = "; ".join(
        p.get("name", "") + " (" + ", ".join(p.get("technologies", [])) + ")"
        for p in resume.get("projects", [])[:4]
    )

    prompt = f"""
You are an expert career advisor evaluating job-candidate fit for a hackathon demo.

CANDIDATE:
- Name: {resume.get('name')}
- Level: {resume.get('candidate_level', 'student')} | Student: {resume.get('is_student')} | Exp: {resume.get('years_of_experience', 0)} yrs
- Location: India (NIT Hamirpur) — can only work remotely or with visa sponsorship
- Education: {edu_str}
- Skills: {skills_str}
- Projects: {projects_str}

SELECTION RULES (strictly enforced):
1. ONLY rank technical/engineering/research roles: ML/AI/data science, software engineering, backend, frontend, DevOps, research
2. NEVER rank admin, coordinator, business partner, HR, sales, marketing, customer support, or any non-engineering role regardless of score
3. If fewer than {top_n} technical roles exist, rank fewer — do NOT fill with non-tech roles

SCORING (use BOTH dimensions — they are independent):
- tech_score (0-100): Skill, project, education alignment ONLY. Ignore location/visa entirely.
  • 80-100: Strong alignment (Python/ML/AI focus matches candidate skills)
  • 60-79:  Moderate alignment (engineering role, partial skill overlap)
  • <60:    Weak alignment — exclude from Top {top_n}
- eligibility_status: Use the pre_eligibility_status as the STARTING POINT. Rules:
  • If pre_eligibility_status = "likely_ineligible" → set to "Ineligible" (do not override)
  • If pre_eligibility_status = "likely_eligible" → set to "Eligible" (unless you see new evidence)
  • If pre_eligibility_status = "requires_verification" → set to "Requires Verification"
  • You may upgrade "requires_verification" to "Eligible" ONLY if you find clear evidence in the description that the role is remote-friendly or India-accessible

RANKING ORDER:
1. tech_score 80+ AND eligibility = Eligible
2. tech_score 80+ AND eligibility = Requires Verification
3. tech_score 60-79 AND eligibility = Eligible
4. Anything below this only if no better options exist

Return ONLY a valid JSON array (no markdown, no commentary):
[
  {{
    "rank": 1,
    "job_id": <id>,
    "title": "job title",
    "company": "company slug",
    "location": "location string",
    "url": "job url",
    "tech_score": <integer 0-100>,
    "eligibility_status": "Eligible | Requires Verification | Ineligible",
    "eligibility_breakdown": [
      "✓ Experience: ...",
      "✓ Education: ...",
      "✓ Location: ...",
      "✓ Work Authorization: ..."
    ],
    "matching_skills": ["Skill1", "Skill2", "Skill3"],
    "gaps": ["Gap1", "Gap2"],
    "match_reason": "2 specific sentences explaining skill and project match."
  }}
]

JOB LISTINGS:
{json.dumps(slim_jobs, indent=2)[:9000]}
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    ranked = json.loads(raw)
    return ranked[:top_n]
