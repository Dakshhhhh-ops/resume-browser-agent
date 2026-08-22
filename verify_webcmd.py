"""
verify_webcmd.py — prove the agent really drives a browser via WebCMD.

    python verify_webcmd.py                       # default: an Airbnb posting
    python verify_webcmd.py <company> <job_id>    # any Greenhouse job

Runs ONLY the explore phase: opens a WebCMD session, loads the real
application form, reads the field list back out of the live DOM, then
closes the session. Nothing is filled and nothing is submitted.
"""

import json
import subprocess
import sys

from browser_agent import _run_webcmd, _webcmd_path

DEFAULT_COMPANY = "airbnb"
DEFAULT_JOB_ID = "8031901"

PROBE_SCRIPT = """
await page.goto(%s, { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(3000);

const captcha = await page.$$eval(
  "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], .g-recaptcha",
  els => els.map(e => (e.getAttribute("src") || e.className).slice(0, 70))
);

const fields = await page.$$eval(
  "input:not([type='hidden']), textarea, select",
  els => els.map(el => ({
    tag: el.tagName.toLowerCase(),
    type: el.type || "",
    name: el.name || "",
    id: el.id || ""
  }))
);

return {
  page_title: await page.title(),
  url: page.url(),
  captcha_nodes: captcha,
  field_count: fields.length,
  fields: fields.slice(0, 15)
};
"""


def main():
    company = sys.argv[1] if len(sys.argv) > 2 else DEFAULT_COMPANY
    job_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_JOB_ID

    url = (
        "https://job-boards.greenhouse.io/embed/job_app"
        f"?for={company}&token={job_id}"
    )

    exe = _webcmd_path()

    if not exe:
        print("webcmd not found. Install it with: npm install -g webcmd")
        print("Or set WEBCMD_PATH to its full path.")
        return 1

    print(f"webcmd binary : {exe}")

    version = subprocess.run(
        [exe, "--version"], capture_output=True, text=True
    )
    print(f"webcmd version: {(version.stdout or version.stderr).strip()}")

    created = subprocess.run(
        [exe, "session", "create", "-f", "json"],
        capture_output=True,
        text=True,
    )

    if created.returncode != 0:
        print(f"Could not create a session: {created.stderr.strip()}")
        return 1

    session_id = json.loads(created.stdout.strip())["id"]
    print(f"session       : {session_id}")
    print(f"exploring     : {url}\n")

    try:
        result = _run_webcmd(session_id, PROBE_SCRIPT % json.dumps(url))

        if not result.get("ok"):
            print(f"FAILED: {result.get('error')}")
            return 1

        data = result["result"]

        print(f"page title    : {data['page_title']}")
        print(f"landed url    : {data['url']}")
        print(f"field count   : {data['field_count']}")
        print(f"captcha       : {data['captcha_nodes'] or 'none detected'}")
        print("\nfirst fields read out of the live DOM:")

        for field in data["fields"]:
            print(
                f"   <{field['tag']} type={field['type'] or '-'}>"
                f" name={field['name'] or '-'}"
                f" id={field['id'] or '-'}"
            )

        if data["captcha_nodes"]:
            print(
                "\nNote: this posting serves a CAPTCHA, so the apply step "
                "will halt here by design rather than automate around it."
            )

        return 0

    finally:
        subprocess.run(
            [exe, "session", "close", session_id],
            capture_output=True,
        )
        print(f"\nsession closed: {session_id}")


if __name__ == "__main__":
    sys.exit(main())
