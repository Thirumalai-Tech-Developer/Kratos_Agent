import base64
import threading

import pytest

from kratos_agent.jobs.browser import ApplicationBrowser, cover_letter, field_answer
from kratos_agent.jobs.manager import JobManager
from kratos_agent.jobs.sources import listing, matching, discover, supported_url
from kratos_agent.jobs.store import JobStore, fingerprint


def profile(store):
    return store.save_profile({"name": "Example Applicant", "email": "applicant@example.test", "skills": ["Python", "PyTorch"],
        "summary": "I built a Python image classification project.", "resume": {"name": "../resume.txt", "data": base64.b64encode(b"Example applicant resume").decode()}})


def role(store=None, **changes):
    job = listing("lever", title="Machine Learning Engineer", company="Example", location="Remote",
                  description="Python and PyTorch. 3 years of experience.", url="https://jobs.lever.co/example/abc", apply_url="https://jobs.lever.co/example/abc/apply", remote=True)
    job.update(changes)
    return matching(job, store.profile() if store else {"skills": ["Python"]}, store.preferences() if store else {"remote_only": False, "locations": [], "keywords": [], "exclude_companies": []})


def test_resume_upload_cannot_choose_a_path_and_profile_does_not_expose_it(tmp_path):
    store = JobStore(tmp_path)
    data = profile(store)
    assert "resume_path" not in data
    assert data["resume_name"] == "resume.txt"
    assert store.resume().parent == store.root / "documents"
    assert not store.missing_profile()
    with pytest.raises(ValueError, match="PDF"):
        store.save_profile({"resume": {"name": "bad.pdf", "data": base64.b64encode(b"not a pdf").decode()}})


def test_dedup_preserves_submitted_status_during_rescan_and_reranking(tmp_path):
    store = JobStore(tmp_path)
    profile(store)
    job = role(store)
    store.upsert(job)
    job_id = fingerprint(job)
    store.set_status(job_id, "submitted", "Confirmed", {"confirmation": "receipt"})
    store.upsert(matching(store.job(job_id), store.profile(), store.preferences()))
    assert store.job(job_id)["status"] == "submitted"
    assert store.job(job_id)["receipt"]["confirmation"] == "receipt"
    with pytest.raises(ValueError):
        store.queue(job_id)
    alias = role(store, company="Example Incorporated")
    alias["apply_url"] += "?utm_source=test"
    store.upsert(alias)
    assert len(store.listings()) == 1
    assert store.counts()["total"] == 1
    assert store.counts()["matches"] == 1


def test_claim_is_atomic_and_daily_limit_counts_uncertain_submissions(tmp_path):
    store = JobStore(tmp_path)
    profile(store)
    one = role(store)
    two = role(store, title="AI Engineer", apply_url="https://jobs.lever.co/example/second/apply")
    for job in (one, two):
        store.upsert(job)
        store.queue(fingerprint(job))
    assert store.claim(fingerprint(one), 1)
    assert not store.claim(fingerprint(one), 10)
    store.set_status(fingerprint(one), "uncertain", "No confirmation")
    assert not store.claim(fingerprint(two), 1)
    assert store.counts()["attempts_today"] == 1


def test_restart_preserves_uncertainty_instead_of_automatically_resubmitting(tmp_path):
    store = JobStore(tmp_path)
    job = role(store)
    store.upsert(job)
    store.queue(fingerprint(job))
    store.claim(fingerprint(job), 5)
    restarted = JobStore(tmp_path)
    restarted.recover()
    assert restarted.job(fingerprint(job))["status"] == "uncertain"
    with pytest.raises(ValueError):
        restarted.queue(fingerprint(job))


def test_matching_handles_location_experience_and_true_skill_overlap(tmp_path):
    store = JobStore(tmp_path)
    profile(store)
    good = role(store)
    assert good["eligible"] and good["score"] >= 70
    limited = {**store.profile(), "years_experience": 1}
    strict = matching(good, limited, {**store.preferences(), "locations": ["Dubai"]})
    assert not strict["eligible"] and len(strict["match_reasons"]) == 2
    unrelated = matching(good, {"skills": ["Rust"]}, store.preferences())
    assert not unrelated["eligible"]


def test_screening_answers_are_not_invented_and_third_party_contact_is_not_filled():
    person = {"name": "Example Applicant", "email": "example@example.test", "country": "UAE", "answers": {"Do you need sponsorship?": "Yes"}}
    assert field_answer({"label": "Do you need sponsorship?", "name": "x", "type": "text"}, person, "letter") == "Yes"
    for label in ("Are you authorized to work in the US?", "Race", "I agree to marketing emails", "Referrer's email"):
        assert field_answer({"label": label, "name": "email", "type": "email" if "Referr" in label else "checkbox"}, person, "letter") is None
    letter = cover_letter({**person, "summary": "I built a Python project."}, role())
    assert "I built a Python project." in letter
    assert "years" not in letter


@pytest.mark.parametrize("url", ["http://jobs.lever.co/test", "https://jobs.lever.co.evil.test/test", "https://127.0.0.1/apply", "https://jobs.lever.co:8443/x", "https://password@jobs.lever.co/x"])
def test_only_supported_https_ats_urls_can_receive_applicant_data(url):
    assert not supported_url(url)


def test_one_broken_feed_does_not_drop_other_source_results(monkeypatch):
    import kratos_agent.jobs.sources as sources
    def fake(source, board, stop):
        if source == "remoteok":
            raise RuntimeError("temporarily unavailable")
        return [listing("arbeitnow", title="AI Engineer", company="Employer", description="Python", url="https://www.arbeitnow.com/view/example")]
    monkeypatch.setattr(sources, "collect_source", fake)
    jobs, reports = discover({"sources": ["remoteok", "arbeitnow"], "boards": {}, "remote_only": False, "locations": [], "exclude_companies": [], "keywords": []}, {"skills": ["Python"]}, threading.Event())
    assert len(jobs) == 1
    assert {item["status"] for item in reports} == {"error", "ok"}


def test_stop_and_start_require_profile_without_launching_external_applications(tmp_path):
    manager = JobManager(tmp_path)
    with pytest.raises(ValueError, match="applicant profile"):
        manager.command("start")
    assert manager.command("stop")["preferences"]["enabled"] is False
    manager.close()


def test_stop_clears_waiting_applications_outside_the_display_limit(tmp_path):
    manager = JobManager(tmp_path)
    job = role(manager.store)
    manager.store.upsert(job)
    manager.store.queue(fingerprint(job))
    # Simulate more historical records than the display can return.
    manager.store.listings = lambda *args: []
    manager.command("stop")
    assert manager.store.job(fingerprint(job))["status"] == "stopped"
    manager.close()


def test_adapter_exception_after_submit_is_uncertain_and_is_not_retried(tmp_path):
    class Adapter:
        calls = 0
        def __init__(self, *args):
            pass
        def apply(self, job, person, resume, before_submit):
            self.calls += 1
            before_submit()
            raise RuntimeError("Connection interrupted after submission")
    manager = JobManager(tmp_path, browser_factory=Adapter)
    profile(manager.store)
    job = role(manager.store)
    manager.store.upsert(job)
    manager.store.queue(fingerprint(job))
    # Avoid pacing in this isolated unit test.
    manager.stop.wait = lambda timeout: False
    manager._apply_queued()
    assert manager.store.job(fingerprint(job))["status"] == "uncertain"
    manager._apply_queued()
    assert manager.store.counts()["attempts_today"] == 1


FORM = '''<html><body><form id="application"><label>Name<input name="name" required></label>
<label>Email<input type="email" name="email" required></label>
<label>Resume<input type="file" name="resume" required style="display:none"></label>
{screening}<button type="submit">Submit application</button></form>
<script>document.querySelector('form').onsubmit=async e=>{{e.preventDefault();await fetch('/test-receipt',{{method:'POST'}});document.body.innerHTML='Thank you for applying';}};</script></body></html>'''


@pytest.mark.parametrize("missing,delayed_combo", [(False, False), (True, False), (False, True)])
def test_real_browser_fills_and_confirms_or_stops_on_missing_screening(tmp_path, missing, delayed_combo):
    posted = []
    class LocalATS(ApplicationBrowser):
        def launch_context(self, playwright, profile_dir):
            context = super().launch_context(playwright, profile_dir)
            def route_handler(route):
                if route.request.method == "POST":
                    posted.append(route.request.url)
                    route.fulfill(status=200, body='{}', content_type='application/json')
                else:
                    screening = '<label>Are you authorized to work in the US?<input name="authorization" required></label>' if missing else ''
                    if delayed_combo:
                        screening = '''<button type="button" role="combobox" aria-label="Country of residence" aria-required="true" onclick="document.querySelector('#options').hidden=false">Choose country</button>
<div id="options" hidden><div role="option" onclick="document.querySelector('[role=combobox]').setAttribute('aria-valuetext','UAE');document.querySelector('#options').hidden=true">UAE</div></div>'''
                    html = FORM.format(screening=screening)
                    if delayed_combo:
                        html = html.replace('<form id="application">', '<form id="application" style="display:none">')
                        html = html.replace('</body>', '<script>setTimeout(()=>document.querySelector("form").style.display="block",400)</script></body>')
                    route.fulfill(status=200, body=html, content_type='text/html')
            context.route('**/*', route_handler)
            return context
        def fill(self, page, person, resume, letter):
            result = super().fill(page, person, resume, letter)
            if delayed_combo:
                assert page.get_by_role('combobox').get_attribute('aria-valuetext') == 'UAE'
            return result
    store = JobStore(tmp_path)
    person = profile(store)
    person['country'] = 'UAE'
    job = {**role(store), "id": fingerprint(role(store))}
    marker = []
    result = LocalATS(store.root, threading.Event()).apply(job, person, store.resume(), lambda: marker.append('submit'))
    assert result['status'] == ('needs_input' if missing else 'submitted'), result
    assert len(posted) == (0 if missing else 1)
    assert len(marker) == (0 if missing else 1)
    assert result['receipt']['screenshot']
