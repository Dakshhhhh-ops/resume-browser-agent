import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
import os
from dotenv import load_dotenv

load_dotenv()

GREENHOUSE_API_BASE = "https://boards-api.greenhouse.io/v1/boards"


def fetch_jobs(company_slug: str, limit: int = 100) -> list[dict]:
    """Fetch job listings for a company from Greenhouse."""
    url = f"{GREENHOUSE_API_BASE}/{company_slug}/jobs?content=true"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs", [])
        return jobs[:limit]
    except requests.HTTPError as e:
        print(f"[!] Could not fetch jobs for '{company_slug}': {e}")
        return []
    except Exception as e:
        print(f"[!] Error fetching '{company_slug}': {e}")
        return []


def fetch_all_jobs(company_slugs: list[str]) -> list[dict]:
    """Fetch jobs from multiple Greenhouse company boards."""
    all_jobs = []
    for slug in company_slugs:
        jobs = fetch_jobs(slug)
        for job in jobs:
            job["_company_slug"] = slug
        all_jobs.extend(jobs)
        print(f"  ✓ {slug}: {len(jobs)} jobs fetched")
    return all_jobs


def get_company_slugs() -> list[str]:
    raw = os.getenv("GREENHOUSE_COMPANY_SLUGS", "airbnb,stripe,figma,dropbox")
    return [s.strip() for s in raw.split(",") if s.strip()]


if __name__ == "__main__":
    from rich import print as rprint
    from rich.table import Table

    slugs = get_company_slugs()
    rprint(f"[bold cyan]Fetching jobs from:[/bold cyan] {slugs}")
    jobs = fetch_all_jobs(slugs)

    table = Table(title=f"Found {len(jobs)} jobs")
    table.add_column("Company", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Location")
    table.add_column("URL", style="dim")

    for j in jobs[:20]:
        loc = j.get("location", {}).get("name", "Remote")
        table.add_row(j["_company_slug"], j["title"], loc, j.get("absolute_url", ""))

    rprint(table)
