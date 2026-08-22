"""
main.py — AI-Powered Job Discovery & WebCMD Application Agent
Usage: python main.py <resume.pdf>
"""

import sys
import io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
from rich import print as rprint
from rich.panel import Panel
from rich.console import Console
from rich.prompt import IntPrompt, Confirm
from dotenv import load_dotenv

load_dotenv()
console = Console()


def main():
    if len(sys.argv) < 2:
        rprint("[bold red]Usage:[/bold red] python main.py <resume.pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        rprint(f"[bold red]File not found:[/bold red] {pdf_path}")
        sys.exit(1)

    # ── Phase 1: Parse Resume ──────────────────────────────────────────────
    rprint(Panel("[bold cyan]Phase 1/3 — Candidate Profile Extraction[/bold cyan]", expand=False))
    from resume_parser import parse_resume
    try:
        with console.status("Parsing resume with Groq LLM..."):
            resume = parse_resume(pdf_path)
    except Exception as e:
        rprint(f"[bold red]Resume Parsing Error:[/bold red] {e}")
        sys.exit(1)

    name = resume.get('name') or 'Candidate'
    edu = resume.get('education', [{}])[0] if resume.get('education') else {}
    degree_str = (
        f"{edu.get('degree', 'Degree')} in {edu.get('field', 'Field')} "
        f"({edu.get('institution', 'University')}, {edu.get('graduation_year', 'N/A')})"
    )
    level_str = (
        "Student / Undergraduate"
        if resume.get("is_student")
        else resume.get("candidate_level", "Entry Level").capitalize()
    )

    rprint(f"  [green]✓[/green] [bold]Name:[/bold]       {name}")
    rprint(f"  [green]✓[/green] [bold]Level:[/bold]      {level_str}")
    rprint(f"  [green]✓[/green] [bold]Education:[/bold]  {degree_str}")
    rprint(f"  [green]✓[/green] [bold]Languages:[/bold]  {', '.join(resume.get('programming_languages', [])[:5])}")
    rprint(f"  [green]✓[/green] [bold]Frameworks:[/bold] {', '.join(resume.get('frameworks', [])[:5])}")
    rprint(f"  [green]✓[/green] [bold]Keywords:[/bold]   {', '.join(resume.get('keywords', [])[:6])}")

    # ── Phase 2: Find & Rank Eligible Jobs ──────────────────────────────────
    rprint(Panel("[bold cyan]Phase 2/3 — Greenhouse Discovery & Eligibility Ranking[/bold cyan]", expand=False))
    from job_search import fetch_all_jobs, get_company_slugs
    from ranker import rank_jobs, filter_eligible_jobs

    slugs = get_company_slugs()
    rprint(f"  [dim]Fetching from: {', '.join(slugs)}[/dim]")
    try:
        all_jobs = fetch_all_jobs(slugs)
    except Exception as e:
        rprint(f"[bold red]Job Search Error:[/bold red] {e}")
        sys.exit(1)

    if not all_jobs:
        rprint("[bold red]No jobs fetched. Please verify GREENHOUSE_COMPANY_SLUGS in .env.[/bold red]")
        sys.exit(1)

    eligible_jobs = filter_eligible_jobs(all_jobs, resume)
    filtered_out_count = len(all_jobs) - len(eligible_jobs)
    rprint(f"  [green]✓[/green] Fetched [bold]{len(all_jobs)}[/bold] total listings across {len(slugs)} companies.")
    rprint(
        f"  [green]✓[/green] [bold yellow]Hard Filter:[/bold yellow] "
        f"Excluded [bold]{filtered_out_count}[/bold] ineligible roles "
        f"(seniority, non-tech domain, 3+ yr experience, non-remote international)."
    )
    rprint(f"  [green]✓[/green] Evaluating [bold]{len(eligible_jobs)}[/bold] candidate listings for Top 3...")

    try:
        with console.status("Evaluating multi-factor eligibility and ranking Top 3 matches..."):
            top_jobs = rank_jobs(resume, all_jobs, top_n=3)
    except Exception as e:
        rprint(f"[bold red]Ranking Error:[/bold red] {e}")
        sys.exit(1)

    if not top_jobs:
        rprint("[yellow]No eligible matches found.[/yellow]")
        sys.exit(0)

    # ── Display Top 3 Job Cards ─────────────────────────────────────────────
    rprint("\n[bold cyan]═══════════════════════════════════════════════════════════════════════[/bold cyan]")
    rprint("[bold green]                       🏆 TOP 3 JOB MATCHES                           [/bold green]")
    rprint("[bold cyan]═══════════════════════════════════════════════════════════════════════[/bold cyan]\n")

    for job in top_jobs:
        tech_score = job.get("tech_score", job.get("match_score", 0))
        score_color = "green" if tech_score >= 80 else "yellow" if tech_score >= 60 else "white"

        eligibility = job.get("eligibility_status", job.get("overall_eligibility", "Requires Verification"))
        elig_icon  = "✓" if eligibility == "Eligible" else "⚠"
        elig_color = "green" if eligibility == "Eligible" else "yellow" if eligibility == "Requires Verification" else "red"

        # Eligibility breakdown lines
        breakdown_items = job.get("eligibility_breakdown", [])
        breakdown_str = (
            "\n".join([f"    {item}" for item in breakdown_items])
            if breakdown_items else
            "    [yellow]⚠[/yellow] Eligibility details unavailable"
        )

        matches_list = "\n".join([f"    [green]✓[/green] {m}" for m in job.get("matching_skills", [])])
        gaps_list = (
            "\n".join([f"    [yellow]⚠[/yellow] {g}" for g in job.get("gaps", [])])
            if job.get("gaps")
            else "    [dim]None identified[/dim]"
        )

        card_content = (
            f"[bold]{job.get('title')}[/bold] — [cyan]{job.get('company')}[/cyan]\n"
            f"[bold]Location:[/bold] {job.get('location', 'Remote')}\n\n"
            # ── Dual-score display ──────────────────────────────────
            f"[bold]Technical Fit:[/bold]  [{score_color}]{tech_score}/100[/{score_color}]  "
            f"[dim](skill, project & education alignment)[/dim]\n"
            f"[bold]Eligibility:   [/bold]  [{elig_color}]{elig_icon} {eligibility}[/{elig_color}]\n\n"
            # ── Breakdown ──────────────────────────────────────────
            f"[bold]Eligibility Breakdown:[/bold]\n{breakdown_str}\n\n"
            f"[bold]Matching Skills:[/bold]\n{matches_list}\n\n"
            f"[bold]Gaps:[/bold]\n{gaps_list}\n\n"
            f"[bold]Why:[/bold] {job.get('match_reason')}\n\n"
            f"[bold]URL:[/bold] [dim]{job.get('url')}[/dim]"
        )

        rprint(Panel(
            card_content,
            title=f"[bold]#{job.get('rank')} Match[/bold]",
            border_style=score_color,
            expand=False,
        ))
        rprint()

    # ── Phase 3: Selection & WebCMD Application ──────────────────────────────
    rprint(Panel("[bold cyan]Phase 3/3 — WebCMD Application Workflow[/bold cyan]", expand=False))
    choice = IntPrompt.ask(
        "Select a job to apply to (1/2/3, or 0 to exit)",
        choices=["0", "1", "2", "3"],
        default=1,
    )

    if choice == 0:
        rprint("\n[yellow]Exiting. No application started.[/yellow]")
        sys.exit(0)

    selected = next((j for j in top_jobs if j.get("rank") == choice), None)
    if not selected:
        rprint("[bold red]Invalid selection.[/bold red]")
        sys.exit(1)

    # Pre-application eligibility confirmation for unresolved items
    eligibility = selected.get("eligibility_status", selected.get("overall_eligibility", ""))
    if eligibility != "Eligible":
        rprint(f"\n[bold yellow]⚠  Unresolved Eligibility Notice[/bold yellow]")
        breakdown = selected.get("eligibility_breakdown", [])
        unresolved = [item for item in breakdown if "⚠" in item]
        if unresolved:
            for item in unresolved:
                rprint(f"  {item}")
        else:
            rprint(f"  [yellow]⚠[/yellow] Status: {eligibility}")
        rprint()
        proceed = Confirm.ask("Proceed to WebCMD browser review anyway?", default=True)
        if not proceed:
            rprint("[yellow]Aborted by user.[/yellow]")
            sys.exit(0)

    from browser_agent import run_browser_agent
    result = run_browser_agent(selected, resume, pdf_path)

    if result.get("success"):
        rprint(f"\n[bold green]{result.get('message')}[/bold green]")
    else:
        rprint(
            f"\n[bold red]Not submitted[/bold red] "
            f"([dim]{result.get('stage')}[/dim]): {result.get('message')}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
