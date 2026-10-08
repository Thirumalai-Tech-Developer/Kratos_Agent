from __future__ import annotations

import re
from pathlib import Path
from threading import Event
from .sources import supported_url
from .store import normalized, now

SUCCESS = re.compile(r"(?:thank you|thanks) for (?:applying|your application)|application (?:has been |was )?(?:successfully )?(?:submitted|received)|successfully submitted your application", re.I)
CHALLENGE = re.compile(r"verify (?:that )?you are human|complete the captcha|verification challenge|unusual traffic|access denied", re.I)
FIELD_SCRIPT = """() => Array.from(document.querySelectorAll('input,textarea,select,[role="combobox"]')).filter(el =>
  (el.getClientRects().length || el.type === 'file') && !el.disabled &&
  (!['hidden','submit','button','reset'].includes(el.type) || el.getAttribute('role') === 'combobox')).map((el, i) => {
  const group = el.closest('fieldset');
  const nativeLabel = Array.from(el.labels || []).map(l => l.innerText).join(' ');
  const labelled = (el.getAttribute('aria-labelledby') || '').split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ');
  const container = el.closest('[class*="field-entry"],[class*="application-field"],[class*="form-group"]');
  const label = (el.type === 'radio' && group?.querySelector('legend')?.innerText) || nativeLabel || labelled ||
    el.getAttribute('aria-label') || container?.querySelector('label')?.innerText || el.placeholder || el.name || el.id || '';
  el.setAttribute('data-kratos-job-field', String(i));
  return {index:i,label:label.trim(),name:el.name || el.id || '',type:el.getAttribute('role') === 'combobox' ? 'combobox' : (el.type || 'text'), nativeType:el.type || '',
    required:!!el.required || el.getAttribute('aria-required') === 'true' || /\\*|required/i.test(label),
    value:el.value || el.getAttribute('aria-valuetext') || '', filled:el.dataset.kratosJobFilled === 'true', checked:!!el.checked, accept:el.accept || '', valid:typeof el.checkValidity === 'function' ? el.checkValidity() : true,
    optionLabel:el.type === 'radio' ? nativeLabel.trim() : '',
    options:el.tagName === 'SELECT' ? Array.from(el.options).map(o => ({label:o.text, value:o.value})) : []};
})"""
READY_SCRIPT = """() => Array.from(document.querySelectorAll('input[type="email"],input[name="email"],input[name="first_name"],button,a')).some(el =>
  el.getClientRects().length && (el.tagName === 'INPUT' || /^apply(?: now| for this job)?$/i.test(el.innerText.trim()))) ||
  /verify (?:that )?you are human|complete the captcha|verification challenge|access denied|(?:sign in|log in) to (?:apply|continue)|no longer (?:accepting|available)|job (?:is )?closed/i.test(document.body.innerText)"""
FORM_READY_SCRIPT = """() => Array.from(document.querySelectorAll('input[type="email"],input[name="email"],input[name="first_name"]')).some(el => el.getClientRects().length) ||
  /verify (?:that )?you are human|complete the captcha|verification challenge|access denied|(?:sign in|log in) to (?:apply|continue)|no longer (?:accepting|available)|job (?:is )?closed/i.test(document.body.innerText)"""


def cover_letter(profile: dict, job: dict) -> str:
    paragraphs = [f"Dear {job['company']} hiring team,", f"I am applying for the {job['title']} position."]
    if profile.get("summary"):
        paragraphs.append(profile["summary"])
    if job.get("matched_skills"):
        paragraphs.append("My relevant skills include " + ", ".join(job["matched_skills"]) + ".")
    paragraphs += ["Please find my resume attached. Thank you for considering my application.", profile["name"]]
    return "\n\n".join(paragraphs)


def field_answer(field: dict, profile: dict, letter: str):
    label = normalized(field["label"])
    name = normalized(field.get("name", ""))
    answers = {normalized(k): v for k, v in profile.get("answers", {}).items()}
    if label in answers:
        return answers[label]
    if name and name in answers:
        return answers[name]
    if re.search(r"referr|reference|emergency|manager|authoriz|sponsor|visa|citizenship|nationality|\brace\b|gender|disabilit|veteran|consent|agree|marketing", label):
        return None
    key = label.rstrip(" *")
    aliases = {"full name": "name", "name": "name", "email": "email", "email address": "email",
               "phone": "phone", "phone number": "phone", "telephone": "phone", "city": "city",
               "country": "country", "country of residence": "country", "current company": "current_company",
               "linkedin": "linkedin", "linkedin profile": "linkedin", "linkedin url": "linkedin",
               "github": "github", "github url": "github", "github profile": "github",
               "portfolio": "portfolio", "portfolio url": "portfolio", "website": "portfolio"}
    if key in ("first name", "firstname") or name in ("first name", "firstname"):
        return profile.get("name", "").split(" ")[0]
    if key in ("last name", "lastname") or name in ("last name", "lastname"):
        return " ".join(profile.get("name", "").split(" ")[1:])
    mapped = aliases.get(key) or aliases.get(name)
    if mapped:
        return profile.get(mapped)
    if key in ("cover letter", "additional information", "additional comments"):
        return letter
    if field["type"] == "email" and "referr" not in key:
        return profile.get("email")
    if field["type"] == "tel" and not re.search(r"emergency|reference|referr", key):
        return profile.get("phone")
    # Authorization, demographics, consent and skills screening need stored answers.
    return None


class ApplicationBrowser:
    def __init__(self, root: Path, stop: Event):
        self.root, self.stop = root, stop

    def check_stop(self):
        if self.stop.is_set():
            raise InterruptedError("Application stopped")

    def launch_context(self, playwright, profile_dir: Path):
        return playwright.chromium.launch_persistent_context(str(profile_dir), headless=True, viewport={"width": 1440, "height": 1000})

    def screenshot(self, page, job_id: str) -> str:
        folder = self.root / "evidence"
        folder.mkdir(mode=0o700, exist_ok=True)
        name = f"{job_id}-{now().replace(':', '-')}.png"
        path = folder / name
        page.screenshot(path=str(path), full_page=False, timeout=5000)
        path.chmod(0o600)
        return "evidence/" + name

    def form_blocker(self, page, job_id: str) -> dict | None:
        if not supported_url(page.url):
            return {"status": "unsupported", "detail": "The form redirected outside supported ATS hosts."}
        text = page.locator("body").inner_text(timeout=8000)
        if CHALLENGE.search(text):
            return {"status": "blocked", "detail": "The employer requires human verification.", "receipt": {"screenshot": self.screenshot(page, job_id)}}
        if re.search(r"(?:sign in|log in) to (?:apply|continue)|create an account to apply", text, re.I):
            return {"status": "needs_login", "detail": "This employer requires an applicant login. Open the original application."}
        if re.search(r"no longer (?:accepting|available)|job (?:is )?closed", text, re.I):
            return {"status": "unsupported", "detail": "This job is no longer accepting applications."}
        return None

    def fill(self, page, profile: dict, resume: Path, letter: str) -> list[str]:
        missing = []
        for field in page.evaluate(FIELD_SCRIPT):
            self.check_stop()
            control = page.locator(f'[data-kratos-job-field="{field["index"]}"]')
            label = normalized(field["label"])
            if field["type"] == "file":
                if re.search(r"\b(resume|cv|curriculum vitae)\b", label + " " + normalized(field["name"])):
                    types = [value.strip().lower() for value in field.get("accept", "").split(",") if value.strip()]
                    mime = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".txt": "text/plain"}[resume.suffix.lower()]
                    if types and resume.suffix.lower() not in types and mime not in types and "*/*" not in types:
                        missing.append("Resume upload requires " + field["accept"])
                        continue
                    control.set_input_files(str(resume), timeout=8000)
                elif field["required"]:
                    missing.append(field["label"] or "Required document upload")
                continue
            answer = field_answer(field, profile, letter)
            if answer is None or answer == "":
                if field["required"] and not field["valid"]:
                    missing.append(field["label"] or field["name"] or "Unnamed required field")
                elif field["required"] and field["type"] == "combobox" and not field["value"]:
                    missing.append(field["label"] or "Required selection")
                continue
            if field["type"] == "checkbox":
                if not isinstance(answer, bool):
                    if field["required"]:
                        missing.append(field["label"] + " (requires a true/false answer)")
                    continue
                control.set_checked(answer, timeout=8000)
            elif field["type"] == "radio":
                text = "yes" if answer is True else "no" if answer is False else str(answer)
                if normalized(field["optionLabel"]) == normalized(text) or normalized(field["value"]) == normalized(text):
                    control.check(timeout=8000)
            elif field["options"]:
                text = "yes" if answer is True else "no" if answer is False else str(answer)
                option = next((o for o in field["options"] if normalized(o["label"]) == normalized(text) or normalized(o["value"]) == normalized(text)), None)
                if option:
                    control.select_option(value=option["value"], timeout=8000)
                else:
                    missing.append(field["label"] + " (answer does not match an option)")
            elif field["type"] == "combobox":
                if field["nativeType"] in ("text", "search"):
                    control.fill(str(answer), timeout=8000)
                control.click(timeout=8000)
                page.get_by_role("option", name=str(answer), exact=True).first.click(timeout=8000)
                control.evaluate("el => el.dataset.kratosJobFilled = 'true'")
            elif field["type"] not in ("password", "search"):
                control.fill(str(answer), timeout=8000)
        # Check again after reactive forms add dependent screening fields.
        for field in page.evaluate(FIELD_SCRIPT):
            if field["required"] and (not field["valid"] or (field["type"] == "combobox" and not field["filled"])):
                missing.append(field["label"] or field["name"] or "Unnamed required field")
        return sorted(set(missing))

    def apply(self, job: dict, profile: dict, resume: Path, before_submit) -> dict:
        if not supported_url(job["apply_url"]):
            return {"status": "unsupported", "detail": "Open the original listing to apply. This host has no supported application adapter."}
        submitted = False
        context = None
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright:
                self.check_stop()
                profile_dir = self.root / "browser"
                profile_dir.mkdir(mode=0o700, exist_ok=True)
                context = self.launch_context(playwright, profile_dir)
                page = context.new_page()
                page.set_default_timeout(8000)
                page.goto(job["apply_url"], wait_until="domcontentloaded", timeout=45000)
                # Hosted React forms often become interactive after DOMContentLoaded.
                page.wait_for_function(READY_SCRIPT, timeout=20000)
                self.check_stop()
                blocker = self.form_blocker(page, job["id"])
                if blocker:
                    return blocker
                if not page.locator('input[type="email"],input[name="email"],input[name="first_name"]').count():
                    button = page.get_by_role("button", name=re.compile(r"^apply(?: now| for this job)?$", re.I))
                    link = page.get_by_role("link", name=re.compile(r"^apply(?: now| for this job)?$", re.I))
                    if button.count():
                        button.first.click()
                    elif link.count():
                        link.first.click()
                    page.wait_for_function(FORM_READY_SCRIPT, timeout=20000)
                blocker = self.form_blocker(page, job["id"])
                if blocker:
                    return blocker
                fields = page.evaluate(FIELD_SCRIPT)
                if not any(field["type"] == "file" and re.search(r"\b(resume|cv|curriculum vitae)\b", normalized(field["label"] + " " + field["name"])) for field in fields):
                    return {"status": "unsupported", "detail": "No supported resume upload was found. Open the original application to complete it manually."}
                letter = cover_letter(profile, job)
                letters = self.root / "letters"
                letters.mkdir(mode=0o700, exist_ok=True)
                (letters / f"{job['id']}.txt").write_text(letter, encoding="utf-8")
                missing = self.fill(page, profile, resume, letter)
                self.check_stop()
                if missing:
                    return {"status": "needs_input", "detail": "Required answers: " + "; ".join(missing),
                            "receipt": {"questions": missing, "screenshot": self.screenshot(page, job["id"])}}
                submit = page.get_by_role("button", name=re.compile(r"^(?:submit(?: application)?|send application|apply for this job)$", re.I))
                if not submit.count():
                    return {"status": "unsupported", "detail": "No supported final application button was found; open this application manually."}
                existing_confirmation = SUCCESS.search(page.locator("body").inner_text())
                self.check_stop()
                before_submit()
                self.check_stop()
                submitted = True
                submit.first.click(timeout=15000)
                # A new, visible receipt is required; a successful HTTP response is insufficient.
                page.wait_for_function("""args => new RegExp(args.pattern,'i').test(document.body.innerText) &&
                  (!args.prior || !Array.from(document.querySelectorAll('input[type="email"],input[name="email"],input[name="first_name"]')).some(el => el.getClientRects().length))""",
                  arg={"pattern": SUCCESS.pattern, "prior": bool(existing_confirmation)}, timeout=30000)
                after = page.locator("body").inner_text()
                match = SUCCESS.search(after)
                if not match:
                    raise RuntimeError("No new application confirmation was visible")
                return {"status": "submitted", "detail": match.group(0), "receipt": {
                    "confirmed_at": now(), "url": page.url, "confirmation": match.group(0), "screenshot": self.screenshot(page, job["id"]),
                }}
        except InterruptedError:
            return {"status": "uncertain" if submitted else "stopped", "detail": "Stop requested. Verify the employer receipt before retrying." if submitted else "Stopped before submission."}
        except Exception as exc:
            return {"status": "uncertain" if submitted else "failed", "detail": ("Submission was attempted; do not retry until its outcome is verified. " if submitted else "") + str(exc)[:600]}
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
