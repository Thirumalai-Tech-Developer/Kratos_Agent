from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from .browser import ApplicationBrowser
from .sources import discover, matching
from .store import JobStore, now

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(self, workspace: Path, browser_factory=ApplicationBrowser, discover_fn=discover):
        self.store = JobStore(workspace)
        self.browser_factory, self.discover_fn = browser_factory, discover_fn
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.shutdown_event = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.scan_requested = False
        self.busy = False
        self.activity = "Idle"
        self.current_job = None
        self.next_scan = time.time()
        self.store.recover()

    def ensure_worker(self):
        with self.lock:
            if not self.thread or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._worker, name="kratos-job-autopilot", daemon=True)
                self.thread.start()
        self.wake.set()

    def status(self) -> dict:
        with self.lock:
            jobs = self.store.listings()
            for job in jobs:
                if len(job["description"]) > 3000:
                    job["description"] = job["description"][:3000] + "… Open the original listing for the full description."
            return {"profile": self.store.profile(), "preferences": self.store.preferences(),
                    "missing_profile": self.store.missing_profile(), "counts": self.store.counts(),
                    "busy": self.busy, "stopping": self.stop.is_set() and self.busy,
                    "activity": self.activity, "current_job": self.current_job,
                    "last_scan": self.store.read("last_scan"), "source_reports": self.store.read("source_reports", []),
                    "jobs": jobs}

    def configure(self, payload: dict) -> dict:
        with self.lock:
            if self.busy:
                raise ValueError("Stop the current job run before editing the applicant profile")
            if "profile" in payload:
                self.store.save_profile(payload["profile"])
            if "preferences" in payload:
                self.store.save_preferences(payload["preferences"])
            profile, preferences = self.store.profile(), self.store.preferences()
            for job in self.store.listings(1000):
                self.store.upsert(matching(job, profile, preferences))
        return self.status()

    def command(self, action: str, job_id: str = "", note: str = "") -> dict:
        with self.lock:
            if action == "stop":
                preferences = self.store.preferences()
                preferences["enabled"] = False
                self.store.write("preferences", preferences)
                self.stop.set()
                self.store.stop_queued()
                self.activity = "Stopping current operation" if self.busy else "Paused"
                self.scan_requested = False
                return self.status()
            if action in ("start", "scan", "apply") and self.stop.is_set() and self.busy:
                raise ValueError("The previous operation is still stopping")
            if action == "start":
                missing = self.store.missing_profile()
                if missing:
                    raise ValueError("Complete your applicant profile: " + ", ".join(missing))
                preferences = self.store.preferences()
                preferences["enabled"] = True
                self.store.write("preferences", preferences)
                self.stop.clear()
                self.scan_requested = True
            elif action == "scan":
                if self.busy:
                    raise ValueError("A job operation is already running")
                self.stop.clear()
                self.scan_requested = True
            elif action == "apply":
                missing = self.store.missing_profile()
                if missing:
                    raise ValueError("Complete your applicant profile: " + ", ".join(missing))
                job = self.store.job(job_id)
                if not job["auto_apply_supported"]:
                    raise ValueError("This application must be opened on its original site")
                if not job["eligible"]:
                    raise ValueError("This job does not match your profile filters")
                self.store.queue(job_id)
                self.stop.clear()
            elif action == "skip":
                job = self.store.job(job_id)
                if job["status"] in ("applying", "submitting", "submitted", "uncertain"):
                    raise ValueError("An active or attempted submission cannot be skipped")
                self.store.set_status(job_id, "skipped", "Skipped by applicant")
            elif action == "confirm_submitted":
                job = self.store.job(job_id)
                if job["status"] != "uncertain" or not note.strip():
                    raise ValueError("Provide the employer confirmation for an uncertain application")
                self.store.set_status(job_id, "submitted", "Confirmed by applicant", {"confirmed_at": now(), "confirmation": note[:2000], "method": "applicant_confirmation"})
            else:
                raise ValueError("Unknown job action")
            if action in ("start", "scan", "apply"):
                self.ensure_worker()
        return self.status()

    def _scan(self):
        self.activity = "Collecting AI and ML roles from job sources"
        jobs, reports = self.discover_fn(self.store.preferences(), self.store.profile(), self.stop)
        if self.stop.is_set():
            return
        for job in jobs:
            self.store.upsert(job)
        self.store.write("source_reports", reports)
        self.store.write("last_scan", now())
        if reports and not any(report["status"] == "ok" for report in reports):
            self.activity = "Job sources unavailable; retrying discovery in 30 minutes"
            self.next_scan = time.time() + 1800
        else:
            self.next_scan = time.time() + self.store.preferences()["interval_minutes"] * 60

    def _apply_queued(self):
        preferences = self.store.preferences()
        profile, resume = self.store.profile(), self.store.resume()
        if self.store.missing_profile() or not resume:
            return
        if preferences["enabled"]:
            for job in self.store.listings(1000, ("discovered",)):
                if job["status"] == "discovered" and job["eligible"] and job["score"] >= preferences["min_score"] and job["auto_apply_supported"]:
                    self.store.queue(job["id"])
        for job in self.store.listings(1000, ("queued",)):
            if self.stop.is_set() or self.shutdown_event.is_set():
                break
            if job["status"] != "queued":
                continue
            if not job["eligible"] or not job["auto_apply_supported"]:
                self.store.set_status(job["id"], "skipped", "This job no longer matches the current profile or supported application sites.")
                continue
            if not self.store.claim(job["id"], preferences["daily_limit"]):
                self.activity = "Daily application limit reached (UTC)"
                break
            self.current_job = job["id"]
            self.activity = f"Applying: {job['title']} · {job['company']}"
            try:
                browser = self.browser_factory(self.store.root, self.stop)
                result = browser.apply(job, profile, resume, lambda: self.store.set_status(job["id"], "submitting", "Final submission initiated"))
                self.store.set_status(job["id"], result["status"], result.get("detail", ""), result.get("receipt"))
            except Exception as exc:
                # A custom adapter may have failed after clicking Submit.
                attempted = self.store.job(job["id"])["status"] == "submitting"
                self.store.set_status(job["id"], "uncertain" if attempted else "failed", str(exc)[:600])
            self.current_job = None
            if self.stop.wait(5):
                break

    def _worker(self):
        while not self.shutdown_event.is_set():
            self.wake.wait(30)
            self.wake.clear()
            with self.lock:
                if self.stop.is_set():
                    continue
                preferences = self.store.preferences()
                scheduled = preferences["enabled"] and time.time() >= self.next_scan
                scan = self.scan_requested or scheduled
                queued = bool(self.store.counts().get("queued"))
                if not scan and not queued:
                    continue
                self.scan_requested = False
                self.busy = True
            try:
                if scan:
                    self._scan()
                if not self.stop.is_set():
                    self._apply_queued()
            except Exception as exc:
                logger.exception("Job workflow failed")
                self.activity = "Job workflow error: " + str(exc)[:300]
                self.next_scan = time.time() + 1800
            finally:
                with self.lock:
                    self.busy = False
                    self.current_job = None
                    if self.stop.is_set():
                        self.activity = "Paused"
                    elif not self.activity.startswith(("Daily", "Job workflow error", "Job sources unavailable")):
                        self.activity = "Waiting for the next scan" if self.store.preferences()["enabled"] else "Idle"

    def close(self):
        self.shutdown_event.set()
        self.stop.set()
        self.wake.set()


_managers: dict[str, JobManager] = {}
_managers_lock = threading.Lock()


def get_manager(workspace: Path) -> JobManager:
    key = str(workspace.resolve())
    with _managers_lock:
        if key not in _managers or _managers[key].shutdown_event.is_set():
            manager = JobManager(workspace)
            _managers[key] = manager
            if manager.store.preferences()["enabled"] or manager.store.counts().get("queued"):
                manager.ensure_worker()
        return _managers[key]
