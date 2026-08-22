"""Quick end-to-end test: parse resume → fetch jobs → rank top 3"""
import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from rich import print as rprint
from rich.panel import Panel
from rich.console import Console

console = Console()

# Phase 1
rprint("[bold cyan]Phase 1: Parsing resume...[/bold cyan]")
from resume_parser import parse_resume
resume = parse_resume("resume.pdf")
rprint(f"  [green]OK[/green] Name: {resume['name']} | Skills: {len(resume['skills'])} extracted")

# Phase 2
rprint("[bold cyan]Phase 2: Fetching jobs...[/bold cyan]")
from job_search import fetch_all_jobs, get_company_slugs
jobs = fetch_all_jobs(get_company_slugs())
rprint(f"  [green]OK[/green] {len(jobs)} jobs fetched")

# Phase 3 - Rank
rprint("[bold cyan]Phase 3: Ranking top 3 jobs with AI...[/bold cyan]")
from ranker import rank_jobs
top3 = rank_jobs(resume, jobs, top_n=3)

rprint("\n[bold yellow]TOP 3 MATCHES[/bold yellow]\n")
for job in top3:
    color = "green" if job["match_score"] >= 70 else "yellow"
    rprint(Panel(
        f"[bold]{job['title']}[/bold] @ {job['company']}\n"
        f"Score: [{color}]{job['match_score']}/100[/{color}]\n"
        f"Why:   {job['match_reason']}\n"
        f"Gap:   [dim]{job.get('gaps', '')}[/dim]\n"
        f"URL:   {job['url']}",
        title=f"#{job['rank']}",
        border_style=color
    ))
