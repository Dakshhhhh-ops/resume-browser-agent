"""
workflow_store.py
Lightweight persistent store for WebCMD-discovered form field workflows.

Explore → Learn → Reuse
  First visit : WebCMD discovers form fields and we save the learned selector map here.
  Later visits: Load the map and skip re-exploration — the agent reuses what it learned.
"""

import json
import os

STORE_PATH = os.path.join(os.path.dirname(__file__), "workflow_store.json")


def load_store() -> dict:
    """Load the full workflow store from disk (returns {} if not found)."""
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_store(store: dict) -> None:
    """Persist the full workflow store to disk."""
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def get_workflow(domain: str) -> dict | None:
    """
    Return the learned field workflow for *domain* (e.g. 'greenhouse.io'),
    or None if we have not explored it yet.
    """
    store = load_store()
    return store.get(domain)


def save_workflow(domain: str, workflow: dict) -> None:
    """
    Persist a newly discovered field workflow for *domain*.
    workflow = {
        "first_name_sel": "input[name='job_application[first_name]']",
        "last_name_sel":  "...",
        "email_sel":      "...",
        "phone_sel":      "...",
        "file_sel":       "input[type='file']",
        "submit_sel":     "input[type='submit']",
        "fields_found":   ["first_name", "last_name", "email", ...],
        "explored_at":    "2026-08-22T02:11:00",
    }
    """
    store = load_store()
    store[domain] = workflow
    save_store(store)


def has_workflow(domain: str) -> bool:
    """Return True if a learned workflow already exists for *domain*."""
    return get_workflow(domain) is not None
