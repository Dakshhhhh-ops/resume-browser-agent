#!/usr/bin/env python
"""
run_server.py — start the Resume Job Agent API.

    python run_server.py            # http://127.0.0.1:8010
    API_PORT=9000 python run_server.py

The React dev server (frontend/) talks to this on port 8010 by default.
"""

import os
import sys

# Make the project root importable so `backend.app.main` can reach
# resume_parser / job_search / ranker / browser_agent at the root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn


def main():
    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8010"))
    reload_enabled = os.getenv("API_RELOAD", "").lower() in {"1", "true", "yes"}

    print(f"Resume Job Agent API -> http://{host}:{port}")
    print(f"Interactive docs      -> http://{host}:{port}/docs")

    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=reload_enabled,
    )


if __name__ == "__main__":
    main()
