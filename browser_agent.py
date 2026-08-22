"""
browser_agent.py

Phase 3:
Explore → Generate Answers → Fill → Verify → Human Approval → Submit
"""

import sys
import io
import os
import json
import base64
import shutil
import subprocess

from datetime import datetime
from dotenv import load_dotenv
from rich import print as rprint
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.prompt import Confirm

import workflow_store as ws

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer,
        encoding="utf-8",
        errors="replace"
    )

load_dotenv()
console = Console()
GREENHOUSE_DOMAIN = "greenhouse.io"


def _webcmd_candidate_dirs() -> list[str]:
    """Directories npm commonly installs global binaries into."""
    dirs = []

    appdata = os.getenv("APPDATA")
    if appdata:
        dirs.append(os.path.join(appdata, "npm"))

    home = os.path.expanduser("~")
    dirs.extend([
        os.path.join(home, ".npm-global", "bin"),
        os.path.join(home, "AppData", "Roaming", "npm"),
        "/usr/local/bin",
    ])

    return [d for d in dirs if os.path.isdir(d)]


def _webcmd_path() -> str | None:
    """
    Resolve the webcmd executable.

    On Windows the npm shim is `webcmd.cmd`, which subprocess cannot
    launch by bare name without shell=True — shutil.which resolves it.
    The npm global directory is also frequently missing from a service
    process PATH, so fall back to the usual install locations.
    """
    override = os.getenv("WEBCMD_PATH")
    if override and os.path.exists(override):
        return override

    found = shutil.which("webcmd")
    if found:
        return found

    for directory in _webcmd_candidate_dirs():
        found = shutil.which("webcmd", path=directory)
        if found:
            return found

    return None


def _run_webcmd(session_id: str, script: str, timeout: int = 90) -> dict:
    exe = _webcmd_path()

    if not exe:
        return {
            "ok": False,
            "error": (
                "webcmd is not installed or not on PATH. "
                "Install it with: npm install -g webcmd"
            ),
        }

    try:
        result = subprocess.run(
            [
                exe,
                "--session",
                session_id,
                "browser",
                "run",
                "--stdin",
                "--no-snapshot-diff",
                "--timeout",
                str(timeout),
            ],
            input=script,
            capture_output=True,
            text=True,
            shell=False,
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if result.returncode != 0:
            return {"ok": False, "error": stderr or stdout or "WebCMD command failed"}

        if not stdout:
            return {"ok": False, "error": stderr or "WebCMD returned no output"}

        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {"ok": False, "error": "Could not parse WebCMD JSON response"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


EXPLORE_SCRIPT_TEMPLATE = r"""
await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(3000);

// Nearly every Greenhouse form embeds *invisible* (score-based) reCAPTCHA,
// which renders only a "protected by reCAPTCHA" badge and asks the user for
// nothing. Treating that badge as a challenge would block every application.
// Only stop when a human challenge is actually being presented.
const captchaState = await page.evaluate(() => {
    const isVisible = (el) => {
        if (!el) return false;
        const r = el.getBoundingClientRect();
        const s = window.getComputedStyle(el);
        return r.width > 50 && r.height > 50 &&
               s.display !== "none" && s.visibility !== "hidden" && s.opacity !== "0";
    };

    // The image-grid overlay shown when a challenge is required.
    const challengeFrame = Array.from(document.querySelectorAll(
        "iframe[src*='bframe'], iframe[src*='hcaptcha.com/captcha']"
    )).some(isVisible);

    // Invisible reCAPTCHA identifies itself with this badge.
    const hasBadge = !!document.querySelector(".grecaptcha-badge");

    // A v2 "I'm not a robot" checkbox renders a widget with no badge.
    const widget = document.querySelector(".g-recaptcha, .h-captcha");
    const checkboxWidget = !hasBadge && isVisible(widget);

    return { challengeFrame, checkboxWidget, hasBadge };
});

if (captchaState.challengeFrame || captchaState.checkboxWidget) {
    return {
        ok: false,
        captcha_detected: true,
        error: "Interactive CAPTCHA challenge detected."
    };
}

const controls = await page.$$eval(
    "input:not([type='hidden']), textarea, select",
    els => els.map(el => {
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        const visible = style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
        if (!visible) return null;

        let labelText = "";
        if (el.id) {
            const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
            if (l) labelText = l.innerText;
        }

        let sel = null;
        if (el.id) sel = `#${CSS.escape(el.id)}`;
        else if (el.name) sel = `[name="${CSS.escape(el.name)}"]`;

        return {
            tag: el.tagName.toLowerCase(),
            type: el.type || "",
            name: el.name || "",
            id: el.id || "",
            sel: sel,
            question_text: String(labelText || "").replace(/\*/g, "").replace(/\s+/g, " ").trim(),
            required: el.required || el.getAttribute("aria-required") === "true"
        };
    }).filter(Boolean)
);

return {
    ok: true,
    page_title: await page.title(),
    url: page.url(),
    invisible_captcha: captchaState.hasBadge,
    fields: controls
};
"""


def explore_current_form(session_id: str, apply_url: str) -> dict | None:
    script = EXPLORE_SCRIPT_TEMPLATE.replace("URL", json.dumps(apply_url))
    result = _run_webcmd(session_id, script, timeout=90)

    if not result.get("ok"):
        rprint(f"[bold red]Explore failed:[/bold red] {result.get('error')}")
        return None

    data = result.get("result", {})
    if data.get("captcha_detected"):
        rprint("[bold red]⚠ CAPTCHA detected. Stopping automation.[/bold red]")
        return None

    return data


def generate_application_answers(required_fields: list, resume: dict, job: dict) -> dict:
    answers = {}
    try:
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return answers

        client = Groq(api_key=api_key)
        questions = [f for f in required_fields if f.get("question_text")]
        if not questions:
            return answers

        prompt = f"""
Answer ONLY using candidate details:
Candidate: {json.dumps(resume, indent=2)}
Job: {json.dumps(job, indent=2)}
Questions: {json.dumps(questions, indent=2)}
Return JSON matching names or selectors.
"""
        response = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0
        )
        answers = json.loads(response.choices[0].message.content)
    except Exception as e:
        rprint(f"[yellow]⚠ LLM answer error: {e}[/yellow]")

    return answers


def _build_fill_script(
    first_name: str,
    last_name: str,
    email: str,
    phone: str,
    pdf_b64: str,
    answers: dict
) -> str:
    return f"""
const fn = {json.dumps(first_name)};
const ln = {json.dumps(last_name)};
const em = {json.dumps(email)};
const ph = {json.dumps(phone)};
const answers = {json.dumps(answers)};

async function safeFill(selectors, val) {{
    if (!val) return false;
    for (const sel of selectors) {{
        try {{
            const el = await page.$(sel);
            if (el) {{
                await el.fill(val);
                return true;
            }}
        }} catch (e) {{}}
    }}
    return false;
}}

await safeFill(["#first_name", "input[name*='first_name']"], fn);
await safeFill(["#last_name", "input[name*='last_name']"], ln);
await safeFill(["#email", "input[type='email']", "input[name*='email']"], em);
await safeFill(["#phone", "input[type='tel']", "input[name*='phone']"], ph);

let resumeAttached = false;
try {{
    const b64 = {json.dumps(pdf_b64)};
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const fileInput = await page.$("input[type='file']");
    if (fileInput) {{
        await page.setInputFiles("input[type='file']", {{
            name: "resume.pdf",
            mimeType: "application/pdf",
            buffer: bytes
        }});
        resumeAttached = true;
    }}
}} catch (e) {{}}

for (const [key, val] of Object.entries(answers)) {{
    await safeFill([key], String(val));
}}

return {{
    success: true,
    first_name_val: await page.$eval("#first_name, input[name*='first_name']", el => el.value).catch(() => ""),
    last_name_val: await page.$eval("#last_name, input[name*='last_name']", el => el.value).catch(() => ""),
    email_val: await page.$eval("#email, input[name*='email']", el => el.value).catch(() => ""),
    phone_val: await page.$eval("#phone, input[name*='phone']", el => el.value).catch(() => ""),
    resume_attached: resumeAttached
}};
"""


def _build_submit_script() -> str:
    return """
const button = await page.$("button[type='submit'], input[type='submit'], #submit_app");
if (!button) return { submitted: false, error: "Submit button missing" };

await button.scrollIntoViewIfNeeded();
await page.waitForTimeout(500);
await button.click();
await page.waitForTimeout(5000);

return {
    submitted: true,
    current_url: page.url(),
    form_still_present: await page.$("input, textarea, select").then(x => !!x).catch(() => false)
};
"""


def _fail(stage: str, message: str, verification: dict | None = None) -> dict:
    """Uniform failure payload shared by the CLI and the API."""
    return {
        "success": False,
        "stage": stage,
        "message": message,
        "verification": verification,
    }


def _applicant_contact(resume: dict) -> tuple[str, str]:
    """
    Resolve contact details.

    Env overrides win over the parsed resume; both the OVERRIDE_*
    and the plain APPLICANT_* names are accepted.
    """
    email = (
        os.getenv("OVERRIDE_APPLICANT_EMAIL")
        or os.getenv("APPLICANT_EMAIL")
        or resume.get("email")
        or ""
    )

    phone = (
        os.getenv("OVERRIDE_APPLICANT_PHONE")
        or os.getenv("APPLICANT_PHONE")
        or resume.get("phone")
        or ""
    )

    return email, phone


def fill_and_handle_application(
    job: dict,
    resume: dict,
    resume_pdf_path: str,
    interactive: bool = True,
    approved: bool = False,
) -> dict:
    """
    Explore -> Generate -> Fill -> Verify -> Approve -> Submit.

    interactive=True  : ask for approval at the terminal (CLI flow)
    interactive=False : never prompt; `approved` must already be True
                        (API flow — the UI is the approval gate)
    """
    job_id = job.get("job_id") or job.get("id")
    company = job.get("company") or job.get("_company_slug")

    if not job_id or not company:
        rprint("[bold red]Job metadata missing.[/bold red]")
        return _fail(
            "metadata",
            "Job is missing its id or company slug.",
        )

    if not _webcmd_path():
        return _fail(
            "webcmd",
            "webcmd is not installed or not on PATH. "
            "Install it with: npm install -g webcmd",
        )

    apply_url = f"https://job-boards.greenhouse.io/embed/job_app?for={company}&token={job_id}"

    if not os.path.exists(resume_pdf_path):
        rprint(f"[bold red]Resume file not found: {resume_pdf_path}[/bold red]")
        return _fail(
            "resume",
            f"Resume file not found: {resume_pdf_path}",
        )

    with open(resume_pdf_path, "rb") as f:
        pdf_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Name: env override wins, then the parsed resume. A single-word name
    # still falls back to "." for the surname, since Greenhouse requires a
    # non-empty last name — set APPLICANT_NAME to avoid that placeholder.
    raw_name = (
        os.getenv("OVERRIDE_APPLICANT_NAME")
        or os.getenv("APPLICANT_NAME")
        or resume.get("name")
        or ""
    ).strip()

    name_parts = raw_name.split()

    first_name = name_parts[0] if name_parts else "Applicant"
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else "."

    email, phone = _applicant_contact(resume)

    rprint(Panel(f"[bold]Applying to:[/bold] {job.get('title')} @ {company}\n[bold]URL:[/bold] {apply_url}", title="🤖 WebCMD Agent", border_style="cyan"))

    session_result = subprocess.run(
        [_webcmd_path(), "session", "create", "-f", "json"],
        capture_output=True,
        text=True,
    )

    if session_result.returncode != 0:
        rprint("[bold red]Failed to launch WebCMD session.[/bold red]")
        return _fail(
            "session",
            (session_result.stderr or "").strip()
            or "Failed to launch a WebCMD browser session.",
        )

    try:
        session_id = json.loads(session_result.stdout.strip())["id"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return _fail(
            "session",
            "Could not read the WebCMD session id from its response.",
        )

    try:
        rprint("\n[bold cyan]🔍 Exploring form fields...[/bold cyan]")
        exploration = explore_current_form(session_id, apply_url)
        if not exploration:
            return _fail(
                "explore",
                "Could not read the application form "
                "(page unreachable or CAPTCHA challenge).",
            )

        fields = exploration.get("fields", [])
        ws.save_workflow(
            GREENHOUSE_DOMAIN,
            {
                "fields": fields,
                "fields_found": [
                    f.get("name") or f.get("id")
                    for f in fields
                    if f.get("name") or f.get("id")
                ],
                "explored_at": datetime.now().isoformat(timespec="seconds"),
            },
        )

        rprint("\n[bold cyan]🧠 Generating custom answers...[/bold cyan]")
        answers = generate_application_answers(fields, resume, job)

        rprint("\n[bold cyan]✍ Filling application...[/bold cyan]")
        fill_script = _build_fill_script(first_name, last_name, email, phone, pdf_b64, answers)
        fill_res = _run_webcmd(session_id, fill_script)

        if not fill_res.get("ok"):
            rprint("[bold red]Filling failed.[/bold red]")
            return _fail(
                "fill",
                fill_res.get("error") or "Filling the form failed.",
            )

        v = fill_res.get("result", {})
        fn_val = v.get("first_name_val", "").strip()
        ln_val = v.get("last_name_val", "").strip()
        em_val = v.get("email_val", "").strip()
        ph_val = v.get("phone_val", "").strip()
        resume_ok = bool(v.get("resume_attached"))

        verification = {
            "first_name": fn_val,
            "last_name": ln_val,
            "email": em_val,
            "phone": ph_val,
            "resume_attached": resume_ok,
        }

        table = Table(title="Browser Field State Verification", border_style="cyan")
        table.add_column("Field")
        table.add_column("Value")
        table.add_column("Status")

        table.add_row("First Name", fn_val, "[green]✓ Populated[/green]" if fn_val else "[red]✖ Empty[/red]")
        table.add_row("Last Name", ln_val, "[green]✓ Populated[/green]" if ln_val else "[red]✖ Empty[/red]")
        table.add_row("Email", em_val, "[green]✓ Populated[/green]" if em_val else "[red]✖ Empty[/red]")
        table.add_row("Phone", ph_val, "[green]✓ Populated[/green]" if ph_val else "[red]✖ Empty[/red]")
        table.add_row("Resume", "Attached" if resume_ok else "Missing", "[green]✓ Attached[/green]" if resume_ok else "[red]✖ Missing[/red]")
        console.print(table)

        # STRICT APPLICATION BLOCK GUARD
        if not (fn_val and ln_val and em_val and resume_ok):
            rprint("\n[bold red]════════════════════════════════════════════[/bold red]")
            rprint("[bold red]APPLICATION BLOCKED: Missing Required Form Fields[/bold red]")
            rprint("Execution aborted because mandatory fields failed browser verification.")
            return _fail(
                "verification",
                "Application blocked: mandatory fields failed browser "
                "verification (name, email or resume attachment).",
                verification,
            )

        # HUMAN APPROVAL GATE
        if interactive:
            rprint("\n[bold yellow]════════════════════════════════════════════[/bold yellow]")
            rprint("[bold yellow]HUMAN APPROVAL REQUIRED[/bold yellow]")
            approved = Confirm.ask("Do you authorize submission?", default=False)

        if not approved:
            rprint("[yellow]Application submission canceled by user.[/yellow]")
            return _fail(
                "approval",
                "Submission was not approved.",
                verification,
            )

        rprint("\n[bold green]✓ Approved. Submitting...[/bold green]")
        submit_res = _run_webcmd(session_id, _build_submit_script())

        if submit_res.get("ok") and submit_res.get("result", {}).get("submitted"):
            rprint(Panel("[bold green]Application Submitted Successfully![/bold green]", title="Complete"))
            return {
                "success": True,
                "stage": "submitted",
                "message": "Application submitted successfully.",
                "verification": verification,
            }

        rprint("[bold red]Submission failed during click execution.[/bold red]")
        return _fail(
            "submit",
            submit_res.get("error")
            or submit_res.get("result", {}).get("error")
            or "Submission failed during click execution.",
            verification,
        )
    finally:
        subprocess.run(
            [_webcmd_path(), "session", "close", session_id],
            capture_output=True,
        )


def run_browser_agent(
    job: dict,
    resume: dict,
    resume_pdf_path: str,
    interactive: bool = True,
    approved: bool = False,
) -> dict:
    return fill_and_handle_application(
        job,
        resume,
        resume_pdf_path,
        interactive=interactive,
        approved=approved,
    )
