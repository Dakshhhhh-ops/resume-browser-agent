# Resume Job Agent

AI-powered job discovery, ranking, and application automation.

Upload a resume PDF → it is parsed into a structured candidate profile with an
LLM → live Greenhouse job boards are searched → roles are hard-filtered and
ranked on a dual score (technical fit + eligibility) → a browser agent fills and
submits the application, behind a human approval gate.

There are two front ends over the same pipeline: a **React web app** and a
**terminal CLI**.

---

## Requirements

- Python 3.11+
- Node.js 18+
- A [Groq](https://console.groq.com/) API key
- `webcmd` (only needed for the apply step): `npm install -g webcmd`

## Setup

```bash
# 1. Configure
cp .env.example .env          # then fill in GROQ_API_KEY

# 2. Python deps
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt   # Windows
# .venv/bin/pip install -r backend/requirements.txt     # macOS / Linux

# 3. Frontend deps
cd frontend && npm install && cd ..
```

## Run the web app

Two terminals:

```bash
# Terminal 1 — API on http://127.0.0.1:8010
python run_server.py

# Terminal 2 — UI on http://localhost:5173
cd frontend && npm run dev
```

Open the UI and walk the four phases: **Analyze Resume → Discover Jobs →
Rank My Top Matches → Apply with Agent**.

Interactive API docs: <http://127.0.0.1:8010/docs>

## Run the CLI

```bash
python main.py resume.pdf
```

Same pipeline, rendered as terminal panels, with the approval prompt inline.

---

## Configuration

All settings live in `.env` (see `.env.example`):

| Variable | Purpose |
| --- | --- |
| `GROQ_API_KEY` | **Required.** Groq API key for parsing and ranking. |
| `GROQ_MODEL` | Model id. Default `openai/gpt-oss-120b`. |
| `GREENHOUSE_COMPANY_SLUGS` | Comma-separated Greenhouse boards to search. |
| `APPLICANT_EMAIL` / `APPLICANT_PHONE` | Override the contact details parsed from the PDF when filling forms. |
| `API_HOST` / `API_PORT` | Where the API binds. Default `127.0.0.1:8010`. |
| `API_RELOAD` | Set to `1` for auto-reload during development. |
| `CORS_ORIGINS` | Origins allowed to call the API. Defaults cover Vite on 5173/5174. |
| `WEBCMD_PATH` | Explicit path to the `webcmd` binary, if it is not on `PATH`. |

The frontend targets `http://127.0.0.1:8010` by default; override it with
`VITE_API_URL` in `frontend/.env.local` (see `frontend/.env.example`).

---

## API

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/api/health` | Status, plus whether Groq is configured. |
| `POST` | `/api/resume/parse` | Multipart PDF upload → structured profile + display summary. Returns a `resume_path` the apply step reuses. |
| `GET` | `/api/jobs` | Fetch and flatten listings from the configured boards. |
| `POST` | `/api/jobs/rank` | `{resume, top_n}` → top matches with `tech_score`, `eligibility_status`, breakdown, skills and gaps. |
| `POST` | `/api/apply` | `{job, resume, resume_path, approved}` → runs the browser agent. |
| `GET` | `/api/applications` | Applications submitted so far. |

Ranking reuses the listings cached by the last `/api/jobs` call, so the full
job descriptions never have to travel to the browser and back. If the cache is
empty (fresh server), it fetches on demand.

## Safety model

Submitting a job application is irreversible, so the apply step is gated twice:

1. **Browser-state verification** — after filling, the agent reads the field
   values back out of the live DOM. If first name, last name, email, or the
   resume attachment did not take, it aborts before submitting.
2. **Human approval** — the CLI asks at the terminal; the API refuses unless
   the caller passes `approved: true`, which the web UI only sends after you
   confirm in the authorization dialog.

CAPTCHA detection also halts automation rather than trying to work around it.

---

## Project layout

```
backend/app/main.py   FastAPI application (all HTTP routes)
run_server.py         API entrypoint
main.py               CLI entrypoint
resume_parser.py      PDF text extraction + LLM profile parsing
job_search.py         Greenhouse board fetching
ranker.py             Hard filter, eligibility pre-screen, LLM ranking
browser_agent.py      WebCMD browser automation (explore → fill → verify → submit)
workflow_store.py     Caches discovered form layouts per domain
frontend/             React + Vite web app
```

Runtime artifacts (`uploads/`, `applications_store.json`, `workflow_store.json`)
are generated on use and git-ignored.
