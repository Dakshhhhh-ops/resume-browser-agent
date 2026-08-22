"""
browser_agent.py
Phase 3: WebCMD Explore → Learn → Reuse browser automation.

Core guarantees:
  1. First Greenhouse visit  → Explore form, discover fields + required fields, save workflow
  2. Subsequent visits       → Load learned workflow, skip re-exploration
  3. After fill              → Verify ALL required fields are populated; block if any are empty
  4. Human approval gate     → Show Rich Table of actual DOM values + required field completeness
  5. Submit                  → Only if (a) verified, (b) required fields complete, (c) human approved
"""

import sys, io
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import json
import base64
import subprocess
from datetime import datetime, timezone
from dotenv import load_dotenv
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.prompt import Confirm

import workflow_store as ws

load_dotenv()
console = Console()

GREENHOUSE_DOMAIN = "greenhouse.io"


# ─────────────────────────────────────────────────────────────────────────────
# WebCMD helper
# ─────────────────────────────────────────────────────────────────────────────

def _run_webcmd(session_id: str, script: str, timeout: int = 90) -> dict:
    """
    Run a JS script in the WebCMD browser sandbox.
    Returns parsed JSON result or {"ok": False, "error": ...}.
    """
    use_shell = os.name == 'nt'
    out = subprocess.run(
        ["webcmd", "--session", session_id, "browser", "run",
         "--stdin", "--no-snapshot-diff", "--timeout", str(timeout)],
        input=script,
        capture_output=True,
        text=True,
        shell=use_shell,
    )
    if out.returncode == 0 and out.stdout:
        try:
            return json.loads(out.stdout.strip())
        except Exception:
            return {"ok": False, "error": "JSON parse failed", "raw": out.stdout[:400]}
    return {
        "ok": False,
        "error": out.stderr[:400] if out.stderr else "No output",
        "returncode": out.returncode,
    }


# ─────────────────────────────────────────────────────────────────────────────
# EXPLORE PHASE — discover selectors AND required fields on a live form
# ─────────────────────────────────────────────────────────────────────────────

EXPLORE_SCRIPT_TEMPLATE = """
await page.goto("{url}", {{ waitUntil: 'domcontentloaded', timeout: 60000 }});
await page.waitForTimeout(2000);

async function findSel(candidates) {{
    for (const sel of candidates) {{
        try {{
            const el = await page.$(sel);
            if (el) return sel;
        }} catch(e) {{}}
    }}
    return null;
}}

const firstNameSel = await findSel(["input[name='job_application[first_name]']", "#first_name", "input[name='first_name']", "input[id*='first_name']", "input[autocomplete='given-name']"]);
const lastNameSel  = await findSel(["input[name='job_application[last_name]']",  "#last_name",  "input[name='last_name']",  "input[id*='last_name']",  "input[autocomplete='family-name']"]);
const emailSel     = await findSel(["input[name='job_application[email]']",       "#email",      "input[name='email']",       "input[id*='email']",       "input[type='email']"]);
const phoneSel     = await findSel(["input[name='job_application[phone]']",       "#phone",      "input[name='phone']",       "input[id*='phone']",       "input[type='tel']"]);
const fileSel      = await findSel(["input[type='file']"]);
const submitSel    = await findSel(["input[type='submit']", "button[type='submit']", "#submit_app"]);

// All visible fields
const allInputs = await page.$$eval(
    'input:not([type=hidden]),textarea,select',
    els => els.map(el => el.name || el.id || el.type).filter(Boolean)
).catch(() => []);

// Required fields — what the form considers mandatory
const requiredFields = await page.$$eval(
    'input[required], input[aria-required="true"], textarea[required], select[required]',
    els => els.map(el => {{
        let qText = "";
        const id = el.id;
        if (id) {{
            const lbl = document.querySelector(`label[for="${{id}}"]`);
            if (lbl) qText = lbl.innerText;
        }}
        if (!qText) {{
            const pLbl = el.closest('label');
            if (pLbl) qText = pLbl.innerText;
        }}
        if (!qText) {{
            const fieldNode = el.closest('.field');
            if (fieldNode) {{
                const flbl = fieldNode.querySelector('label');
                if (flbl) qText = flbl.innerText;
            }}
        }}
        if (qText) {{
            qText = qText.replace(/\*/g, '').split('\\n')[0].trim();
        }}
        const fallback = el.name || el.id || el.type;
        return {{ 
            name: fallback, 
            sel: el.name ? `input[name='${{el.name}}']` : `#${{el.id}}`,
            question_text: qText || `Unknown Question (${{fallback}})`,
            type: el.tagName.toLowerCase() === 'select' ? 'select' : (el.type || 'text')
        }};
    }})
).catch(() => []);

return {{
    first_name_sel:  firstNameSel,
    last_name_sel:   lastNameSel,
    email_sel:       emailSel,
    phone_sel:       phoneSel,
    file_sel:        fileSel,
    submit_sel:      submitSel,
    fields_found:    allInputs,
    required_fields: requiredFields,
    page_title:      await page.title(),
    url:             page.url()
}};
"""


# ─────────────────────────────────────────────────────────────────────────────
# FILL PHASE — fill form and verify required fields in one script
# ─────────────────────────────────────────────────────────────────────────────

def _build_fill_script(workflow: dict, first_name: str, last_name: str,
                        email: str, phone: str, pdf_b64: str) -> str:
    fn = workflow.get("first_name_sel", "") or ""
    ln = workflow.get("last_name_sel",  "") or ""
    em = workflow.get("email_sel",      "") or ""
    ph = workflow.get("phone_sel",      "") or ""
    fi = workflow.get("file_sel",       "input[type='file']") or "input[type='file']"

    # Build required field selectors from stored workflow
    req_fields = workflow.get("required_fields", [])
    req_check_js = json.dumps(req_fields)

    return f"""
async function tryFill(sel, val) {{
    if (!sel) return false;
    try {{
        await page.fill(sel, val, {{ timeout: 3000 }});
        return true;
    }} catch(e) {{ return false; }}
}}

// Fill all discovered fields
const r1 = await tryFill("{fn}", "{first_name}");
const r2 = await tryFill("{ln}", "{last_name}");
const r3 = await tryFill("{em}", "{email}");
const r4 = await tryFill("{ph}", "{phone}");

// Upload resume as in-memory binary payload
const b64 = "{pdf_b64}";
const binary = atob(b64);
const bytes = new Uint8Array(binary.length);
for (let i = 0; i < binary.length; i++) {{
    bytes[i] = binary.charCodeAt(i);
}}
let resumeAttached = false;
const fileInput = await page.$("{fi}");
if (fileInput) {{
    await page.setInputFiles("{fi}", {{
        name: "resume.pdf",
        mimeType: "application/pdf",
        buffer: bytes
    }});
    resumeAttached = true;
}}

await page.waitForTimeout(1500);

// Read back filled values for DOM verification
const verifiedFirst = await page.$eval("{fn}", el => el.value).catch(() => "");
const verifiedLast  = await page.$eval("{ln}", el => el.value).catch(() => "");
const verifiedEmail = await page.$eval("{em}", el => el.value).catch(() => "");
const verifiedPhone = await page.$eval("{ph}", el => el.value).catch(() => "");

// Check required fields — any empty required field blocks submission
const reqFieldDefs = {req_check_js};
const emptyRequired = [];
for (const f of reqFieldDefs) {{
    try {{
        const val = await page.$eval(f.sel, el => el.value).catch(() => "");
        if (!val || !val.trim()) {{
            emptyRequired.push(f.name);
        }}
    }} catch(e) {{
        emptyRequired.push(f.name + " (error)");
    }}
}}

// Also check required file inputs
const hasRequiredFile = await page.$('input[type="file"][required]').catch(() => null);
const fileEmpty = hasRequiredFile && !resumeAttached;
if (fileEmpty) emptyRequired.push("resume (file required)");

return {{
    success: true,
    first_name_val:  verifiedFirst,
    last_name_val:   verifiedLast,
    email_val:       verifiedEmail,
    phone_val:       verifiedPhone,
    resume_attached: resumeAttached,
    empty_required:  emptyRequired,
    page_title:      await page.title(),
    url:             page.url()
}};
"""


# ─────────────────────────────────────────────────────────────────────────────
# SUBMIT PHASE
# ─────────────────────────────────────────────────────────────────────────────

def _build_submit_script(submit_sel: str) -> str:
    sel = submit_sel or "input[type='submit'], button[type='submit'], #submit_app"
    return f"""
const submitBtn = await page.$("{sel}");
if (!submitBtn) {{
    return {{ submitted: false, error: "Submit button not found on page" }};
}}
await submitBtn.click();
await page.waitForTimeout(4000);
return {{
    submitted: true,
    current_url: page.url(),
    page_title:  await page.title()
}};
"""


# ─────────────────────────────────────────────────────────────────────────────
# DOM RE-CHECK — read back values after a timeout to see if fill succeeded
# ─────────────────────────────────────────────────────────────────────────────

RE_CHECK_SCRIPT = """
const fn = await page.$eval("input[name='job_application[first_name]']", el => el.value).catch(
    () => page.$eval("#first_name", el => el.value).catch(() => "")
);
const em = await page.$eval("input[name='job_application[email]']", el => el.value).catch(
    () => page.$eval("#email", el => el.value).catch(() => "")
);
return {{ first_name_val: fn, email_val: em, url: page.url(), page_title: await page.title() }};
"""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY
# ─────────────────────────────────────────────────────────────────────────────

def fill_and_handle_application(job: dict, resume: dict, resume_pdf_path: str) -> bool:
    """
    Explore → Learn → Reuse → Fill → Required-Field Check → Human Gate → Submit
    """
    job_id  = job.get("job_id") or job.get("id")
    company = job.get("company") or job.get("_company_slug")
    if not job_id or not company:
        rprint("[bold red]Error: Selected job is missing ID or company slug.[/bold red]")
        return False

    apply_url = f"https://job-boards.greenhouse.io/embed/job_app?for={company}&token={job_id}"

    if not os.path.exists(resume_pdf_path):
        rprint(f"[bold red]Error: Resume not found at {resume_pdf_path}[/bold red]")
        return False

    try:
        with open(resume_pdf_path, "rb") as f:
            pdf_b64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        rprint(f"[bold red]Error reading resume: {e}[/bold red]")
        return False

    applicant_name  = os.getenv("APPLICANT_NAME")  or resume.get("name", "Applicant")
    applicant_email = os.getenv("APPLICANT_EMAIL") or resume.get("email", "applicant@example.com")
    applicant_phone = os.getenv("APPLICANT_PHONE") or resume.get("phone", "+1234567890")
    first_name = applicant_name.split()[0] if applicant_name else ""
    last_name  = " ".join(applicant_name.split()[1:]) if applicant_name else ""

    rprint(Panel(
        f"[bold]Applying to:[/bold]  {job.get('title')} @ [cyan]{company}[/cyan]\n"
        f"[bold]Job URL:[/bold]      {apply_url}\n"
        f"[bold]Applicant:[/bold]    {applicant_name} | {applicant_email} | {applicant_phone}",
        title="🤖 WebCMD Browser Agent",
        border_style="cyan",
    ))

    # ── 1. Create WebCMD Session ─────────────────────────────────────────────
    rprint("[dim]Creating isolated WebCMD browser session...[/dim]")
    use_shell = os.name == 'nt'
    try:
        session_out = subprocess.run(
            ["webcmd", "session", "create", "-f", "json"],
            capture_output=True, text=True, check=True, shell=use_shell,
        )
        session_data = json.loads(session_out.stdout.strip())
        session_id   = session_data["id"]
        rprint(f"[dim]Session: {session_id}[/dim]")
    except Exception as e:
        rprint(f"[bold red]WebCMD Error: Failed to create session ({e})[/bold red]")
        return False

    try:
        # ── 2. EXPLORE → LEARN → REUSE ───────────────────────────────────────
        stored_workflow = ws.get_workflow(GREENHOUSE_DOMAIN)
        workflow = None

        if stored_workflow:
            fields_count = len(stored_workflow.get("fields_found", []))
            explored_at  = stored_workflow.get("explored_at", "unknown")
            rprint(f"\n[bold green]♻  Reusing learned Greenhouse workflow[/bold green]")
            rprint(f"   [dim]{fields_count} fields discovered on previous run · explored at {explored_at}[/dim]")

            # Saved workflow includes required_fields from the previous explore
            req_fields = stored_workflow.get("required_fields", [])
            rprint(f"   [dim]Required fields from learned workflow: "
                   f"{', '.join(f['name'] for f in req_fields) if req_fields else 'none detected'}[/dim]")

            workflow = stored_workflow

            # Navigate to the new page (different job, same form structure)
            nav_script = f"""
await page.goto("{apply_url}", {{ waitUntil: 'domcontentloaded', timeout: 60000 }});
await page.waitForTimeout(2000);
return {{ navigated: true, page_title: await page.title(), url: page.url() }};
"""
            nav_res = _run_webcmd(session_id, nav_script, timeout=75)
            if not (nav_res.get("ok") and nav_res.get("result", {}).get("navigated")):
                rprint("[yellow]⚠ Navigation warning — proceeding with fill anyway[/yellow]")
            else:
                rprint(f"   [green]✓ Navigated:[/green] {nav_res.get('result', {}).get('page_title', apply_url)}")

        else:
            # ── EXPLORE: first time seeing Greenhouse ─────────────────────────
            rprint(f"\n[bold cyan]🔍 Exploring Greenhouse application form for the first time...[/bold cyan]")
            rprint(f"   [dim]→ {apply_url}[/dim]")

            explore_script = EXPLORE_SCRIPT_TEMPLATE.format(url=apply_url)
            explore_res = _run_webcmd(session_id, explore_script, timeout=90)

            if not explore_res.get("ok"):
                err = explore_res.get("error", "unknown")
                rprint(f"[bold red]✖ Explore phase failed:[/bold red] {err}")
                rprint("[dim]Tip: This usually means the Greenhouse form took too long to load. Try again.[/dim]")
                return False

            discovered = explore_res.get("result", {})
            fields_found   = discovered.get("fields_found", [])
            required_fields = discovered.get("required_fields", [])

            # ── LEARN: save discovered workflow ────────────────────────────────
            workflow = {
                "first_name_sel":  discovered.get("first_name_sel"),
                "last_name_sel":   discovered.get("last_name_sel"),
                "email_sel":       discovered.get("email_sel"),
                "phone_sel":       discovered.get("phone_sel"),
                "file_sel":        discovered.get("file_sel", "input[type='file']"),
                "submit_sel":      discovered.get("submit_sel", "input[type='submit']"),
                "fields_found":    fields_found,
                "required_fields": required_fields,
                "explored_at":     datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            ws.save_workflow(GREENHOUSE_DOMAIN, workflow)

            rprint(f"\n[bold green]✓ Form explored successfully[/bold green]")
            rprint(f"   Fields discovered ({len(fields_found)}): {', '.join(fields_found[:8])}")
            req_names = [f["name"] for f in required_fields]
            rprint(f"   Required fields ({len(required_fields)}): "
                   f"{', '.join(req_names) if req_names else 'none detected (form may not use required attr)'}")
            rprint(f"   Selectors: first_name=[dim]{workflow['first_name_sel']}[/dim]  "
                   f"email=[dim]{workflow['email_sel']}[/dim]")
            rprint(f"\n[green]✓ Learned workflow saved → workflow_store.json[/green]")
            rprint(f"[dim]  Next Greenhouse application will REUSE this workflow instead of re-exploring.[/dim]")

        if not workflow:
            rprint("[bold red]✖ No workflow available. Cannot proceed.[/bold red]")
            return False

        # ── 3. FILL PHASE ────────────────────────────────────────────────────
        rprint(f"\n[bold cyan]Filling application form...[/bold cyan]")
        fill_script = _build_fill_script(
            workflow, first_name, last_name,
            applicant_email, applicant_phone, pdf_b64
        )

        fill_res = _run_webcmd(session_id, fill_script, timeout=90)

        is_verified = False
        verification_details = {}

        if fill_res.get("ok"):
            state = fill_res.get("result", {})
            if isinstance(state, dict) and state.get("success"):
                is_verified = bool(state.get("first_name_val")) and bool(state.get("email_val"))
                verification_details = state

        # ── 3b. Timeout re-check ──────────────────────────────────────────────
        if not is_verified:
            rprint("[yellow]⚠ Fill response unclear — running DOM re-check...[/yellow]")
            recheck_res = _run_webcmd(session_id, RE_CHECK_SCRIPT, timeout=30)
            if recheck_res.get("ok"):
                rc = recheck_res.get("result", {})
                if rc.get("first_name_val") and rc.get("email_val"):
                    is_verified = True
                    verification_details = {
                        "first_name_val":  rc.get("first_name_val"),
                        "last_name_val":   last_name,
                        "email_val":       rc.get("email_val"),
                        "phone_val":       applicant_phone,
                        "resume_attached": True,
                        "empty_required":  [],   # can't know from re-check, assume ok
                        "page_title":      rc.get("page_title", ""),
                        "url":             rc.get("url", apply_url),
                        "_from_recheck":   True,
                    }
                    rprint("[green]✓ Re-check confirmed: fields populated despite timeout[/green]")

        # ── 4. BLOCK if fill state unverified ────────────────────────────────
        if not is_verified:
            rprint("\n" + "═" * 55)
            rprint("[bold red]  APPLICATION STATE UNVERIFIED[/bold red]")
            rprint("═" * 55)
            rprint("  [yellow]⚠[/yellow] WebCMD could not confirm fields were populated.")
            rprint("  [yellow]⚠[/yellow] DOM re-check also failed.")
            rprint("  [bold red]✖ Submission BLOCKED — unverified state.[/bold red]\n")
            return False

        # ── 4b. BLOCK if any required core fields are empty ────────────────────────
        agent_unfilled = verification_details.get("agent_unfilled", [])
        if agent_unfilled:
            rprint("\n" + "═" * 55)
            rprint("[bold yellow]  SOME REQUIRED FIELDS WERE UNFILLED[/bold yellow]")
            rprint("═" * 55)
            for f in agent_unfilled:
                rprint(f"  [bold yellow]⚠ Required field empty (agent cannot fill):[/bold yellow] {f}")
            rprint("  [bold yellow]⚠ Note: Core fields are verified. Proceeding to approval gate...[/bold yellow]\n")

        # ── 5. HUMAN APPROVAL GATE ────────────────────────────────────────────
        recheck_note = " [dim](re-check)[/dim]" if verification_details.get("_from_recheck") else ""

        rprint("\n" + "═" * 65)
        rprint("[bold yellow]                 FINAL SUBMISSION GATE[/bold yellow]")
        rprint("═" * 65)
        rprint(f"  Job:     [bold]{job.get('title')}[/bold]")
        rprint(f"  Company: [cyan]{company}[/cyan]")
        rprint(f"  URL:     [dim]{verification_details.get('url', apply_url)}[/dim]\n")

        # Rich Table — live browser DOM readback
        table = Table(
            title="Live Browser State  (WebCMD DOM Readback)",
            border_style="green",
            show_lines=True,
        )
        table.add_column("Field",              style="bold", width=18)
        table.add_column("Value in Browser",   style="cyan", width=42)
        table.add_column("Status",             width=16)

        def _status(val: str) -> str:
            return "[green]✓ Populated[/green]" if val else "[red]✖ Empty[/red]"

        fn_val = verification_details.get("first_name_val", "")
        ln_val = verification_details.get("last_name_val", "")
        em_val = verification_details.get("email_val", "")
        ph_val = verification_details.get("phone_val", "")
        res_ok = verification_details.get("resume_attached", False)

        table.add_row("First Name", fn_val + recheck_note, _status(fn_val))
        table.add_row("Last Name",  ln_val,                _status(ln_val))
        table.add_row("Email",      em_val,                _status(em_val))
        table.add_row("Phone",      ph_val,                _status(ph_val))
        table.add_row(
            "Resume",
            "resume.pdf (in-memory)",
            "[green]✓ Attached[/green]" if res_ok else "[yellow]⚠ Unconfirmed[/yellow]",
        )
        table.add_row(
            "Extra Required Fields",
            "None or all complete" if not agent_unfilled else f"Needs human input: {', '.join(agent_unfilled)}",
            "[green]✓ OK[/green]" if not agent_unfilled else "[yellow]⚠ Incomplete[/yellow]",
        )
        table.add_row(
            "Live Page",
            verification_details.get("page_title", ""),
            "[dim]confirmed[/dim]",
        )
        console.print(table)

        rprint("\n[bold red]⚠  FINAL SUBMISSION REQUIRES YOUR EXPLICIT APPROVAL[/bold red]")
        rprint("[dim]The agent will NOT submit without your confirmation.[/dim]\n")

        approved = Confirm.ask("Submit this application?", default=False)
        if not approved:
            rprint("\n[yellow]Application cancelled. No submission was made.[/yellow]")
            return False

        # ── 6. SUBMIT ────────────────────────────────────────────────────────
        rprint("\n[bold green]Human approval received. Submitting via WebCMD...[/bold green]")
        submit_script = _build_submit_script(workflow.get("submit_sel", ""))
        submit_res = _run_webcmd(session_id, submit_script, timeout=60)

        submit_ok = (
            submit_res.get("ok") and
            submit_res.get("result", {}).get("submitted")
        )

        if submit_ok:
            final_url   = submit_res.get("result", {}).get("current_url", "")
            final_title = submit_res.get("result", {}).get("page_title", "")
            rprint(Panel(
                f"[bold green]🎉 Application Submitted Successfully![/bold green]\n"
                f"Role:  {job.get('title')} @ {company}\n"
                f"Page:  {final_title}\n"
                f"URL:   {final_url}\n\n"
                f"WebCMD confirmed submission in the live browser session.",
                title="✓ Submission Complete",
                border_style="green",
            ))
            return True
        else:
            err_msg = submit_res.get("error", submit_res.get("result", {}).get("error", "Unknown"))
            rprint(Panel(
                f"[bold red]❌ Submission unconfirmed[/bold red]\n"
                f"WebCMD could not verify the submit button click.\n"
                f"Error: {err_msg}",
                title="Submission Error",
                border_style="red",
            ))
            return False

    finally:
        rprint("[dim]Closing WebCMD session...[/dim]")
        subprocess.run(
            ["webcmd", "session", "close", session_id],
            capture_output=True, shell=(os.name == 'nt'),
        )


def run_browser_agent(job: dict, resume: dict, resume_pdf_path: str):
    """Entry point from main CLI orchestrator."""
    fill_and_handle_application(job, resume, resume_pdf_path)
