from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

import os
import re
import sys
import json
import uuid


# ============================================================
# PROJECT ROOT
# ============================================================

ROOT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv(os.path.join(ROOT_DIR, ".env"))


# ============================================================
# PROJECT IMPORTS
# ============================================================

from resume_parser import parse_resume
from job_search import fetch_all_jobs, get_company_slugs
from ranker import rank_jobs
from browser_agent import run_browser_agent


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Resume Browser Agent",
    description="AI-powered job discovery, ranking and application automation",
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

def get_cors_origins():
    # 5174 is Vite's fallback port when 5173 is already taken.
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174",
    )

    return [
        origin.strip()
        for origin in raw.split(",")
        if origin.strip()
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# STORAGE PATHS
# ============================================================

UPLOAD_DIR = os.path.join(ROOT_DIR, "uploads")

APPLICATIONS_FILE = os.path.join(
    ROOT_DIR,
    "applications_store.json",
)

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ============================================================
# JOB CACHE
#
# Greenhouse listings carry full HTML descriptions. Ranking
# needs them, the browser does not — so the raw listings stay
# here and only slim cards go over the wire.
# ============================================================

_JOB_CACHE: list[dict] = []


# ============================================================
# APPLICATION STORAGE
# ============================================================

def load_applications():
    if not os.path.exists(APPLICATIONS_FILE):
        return []

    try:
        with open(
            APPLICATIONS_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except Exception:
        return []


def save_application(application):
    applications = load_applications()

    job_id = str(
        application.get("job_id", "")
    )

    if any(
        str(item.get("job_id", "")) == job_id
        for item in applications
    ):
        return

    applications.append(application)

    with open(
        APPLICATIONS_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            applications,
            f,
            indent=2,
        )


# ============================================================
# NORMALISERS
# ============================================================

def slim_job(job: dict) -> dict:
    """Flatten a raw Greenhouse listing into a UI-friendly card."""

    location = job.get("location") or {}

    if isinstance(location, dict):
        location = location.get("name", "")

    company = (
        job.get("_company_slug")
        or job.get("company")
        or ""
    )

    job_id = job.get("id")

    url = job.get("absolute_url") or (
        f"https://job-boards.greenhouse.io/embed/job_app"
        f"?for={company}&token={job_id}"
    )

    description = re.sub(
        r"<[^>]+>",
        " ",
        job.get("content") or "",
    )

    description = re.sub(r"\s+", " ", description).strip()

    return {
        "job_id": job_id,
        "title": job.get("title", ""),
        "company": company,
        "location": location or "Not specified",
        "url": url,
        "description": description[:400],
    }


def summarise_profile(profile: dict) -> dict:
    """Flatten the parsed resume into the fields the UI displays."""

    education = profile.get("education") or []
    first = education[0] if education else {}

    education_str = "—"

    if first:
        education_str = (
            f"{first.get('degree') or 'Degree'} in "
            f"{first.get('field') or 'Field'} — "
            f"{first.get('institution') or 'Institution'}"
            f" ({first.get('graduation_year') or 'N/A'})"
        )

    if profile.get("is_student"):
        level = "Student / Undergraduate"
    else:
        level = str(
            profile.get("candidate_level") or "Entry Level"
        ).replace("-", " ").title()

    return {
        "name": profile.get("name") or "Candidate",
        "email": profile.get("email") or "—",
        "phone": profile.get("phone") or "—",
        "level": level,
        "education": education_str,
        "years_of_experience": profile.get(
            "years_of_experience", 0
        ),
        "languages": profile.get(
            "programming_languages", []
        )[:8],
        "frameworks": profile.get("frameworks", [])[:8],
        "keywords": profile.get("keywords", [])[:10],
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "success": True,
        "message": "Resume Browser Agent API is running",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():
    return {
        "status": "healthy",
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "companies": get_company_slugs(),
    }


# ============================================================
# RESUME PARSING
# ============================================================

@app.post("/api/resume/parse")
async def parse_resume_api(
    file: UploadFile = File(...),
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file was uploaded.",
        )

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF resumes are supported.",
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty.",
        )

    # The PDF is kept on disk: the apply step re-uploads this
    # exact file into the Greenhouse form later on.
    resume_path = os.path.join(
        UPLOAD_DIR,
        f"{uuid.uuid4().hex}.pdf",
    )

    with open(resume_path, "wb") as f:
        f.write(content)

    try:
        profile = parse_resume(resume_path)

    except Exception as e:
        if os.path.exists(resume_path):
            os.remove(resume_path)

        raise HTTPException(
            status_code=500,
            detail=f"Resume parsing failed: {e}",
        )

    return {
        "success": True,
        "resume_path": resume_path,
        "profile": profile,
        "summary": summarise_profile(profile),
    }


# ============================================================
# JOB DISCOVERY
# ============================================================

@app.get("/api/jobs")
def get_jobs():
    global _JOB_CACHE

    try:
        slugs = get_company_slugs()

        jobs = fetch_all_jobs(slugs)

    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"Job discovery failed: {e}",
        )

    if not jobs:
        raise HTTPException(
            status_code=502,
            detail=(
                "No jobs returned. Check GREENHOUSE_COMPANY_SLUGS "
                "in your .env file."
            ),
        )

    _JOB_CACHE = jobs

    return {
        "success": True,
        "count": len(jobs),
        "companies": slugs,
        "jobs": [slim_job(job) for job in jobs],
    }


# ============================================================
# JOB RANKING
# ============================================================

@app.post("/api/jobs/rank")
def rank_jobs_api(payload: dict):
    global _JOB_CACHE

    resume = payload.get("resume")
    jobs = payload.get("jobs") or _JOB_CACHE
    top_n = payload.get("top_n", 3)

    if not resume:
        raise HTTPException(
            status_code=400,
            detail="Resume profile is required.",
        )

    if not jobs:
        # Nothing discovered yet in this process — fetch on demand
        # so ranking works even after a server restart.
        try:
            jobs = fetch_all_jobs(get_company_slugs())
            _JOB_CACHE = jobs

        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Job discovery failed: {e}",
            )

    if not jobs:
        raise HTTPException(
            status_code=400,
            detail="Job list is empty. Discover jobs first.",
        )

    try:
        ranked = rank_jobs(
            resume,
            jobs,
            top_n=top_n,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ranking failed: {e}",
        )

    return {
        "success": True,
        "count": len(ranked),
        "jobs": ranked,
    }


# ============================================================
# APPLICATIONS
# ============================================================

@app.get("/api/applications")
def get_applications():
    applications = load_applications()

    return {
        "success": True,
        "count": len(applications),
        "applications": applications,
    }


# ============================================================
# APPLY TO JOB
# ============================================================

@app.post("/api/apply")
def apply_to_job(payload: dict):
    job = payload.get("job")
    resume = payload.get("resume")
    resume_path = payload.get("resume_path")
    approved = bool(payload.get("approved"))

    if not job:
        raise HTTPException(
            status_code=400,
            detail="Job is required.",
        )

    if not resume:
        raise HTTPException(
            status_code=400,
            detail="Resume profile is required.",
        )

    if not resume_path:
        raise HTTPException(
            status_code=400,
            detail="Resume path is required.",
        )

    if not os.path.exists(resume_path):
        raise HTTPException(
            status_code=400,
            detail=(
                "Uploaded resume no longer exists on the server. "
                "Please re-upload your resume."
            ),
        )

    if not approved:
        # The human approval gate: the CLI asks at the terminal,
        # the API requires the caller to say so explicitly.
        raise HTTPException(
            status_code=400,
            detail=(
                "Submission not approved. Send approved=true to "
                "authorise the agent to submit this application."
            ),
        )

    try:
        result = run_browser_agent(
            job,
            resume,
            resume_path,
            interactive=False,
            approved=True,
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

    if not result.get("success"):
        return {
            "success": False,
            "stage": result.get("stage"),
            "message": result.get(
                "message",
                "Application was not submitted.",
            ),
            "verification": result.get("verification"),
        }

    application = {
        "job_id": str(
            job.get("job_id")
            or job.get("id")
            or ""
        ),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "url": job.get("url", ""),
        "status": "Submitted",
    }

    save_application(application)

    return {
        "success": True,
        "message": "Application submitted successfully.",
        "verification": result.get("verification"),
        "application": application,
    }
