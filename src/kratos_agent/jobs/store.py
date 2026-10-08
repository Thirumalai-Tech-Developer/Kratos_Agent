from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULTS = {
    "enabled": False, "interval_minutes": 360, "daily_limit": 5,
    "min_score": 70, "remote_only": False, "locations": [],
    "exclude_companies": [], "keywords": [],
    "sources": ["remoteok", "arbeitnow", "greenhouse", "lever", "ashby"],
    "boards": {"greenhouse": ["anthropic", "huggingface", "scaleai"],
               "lever": ["mistral", "cohere"], "ashby": ["openai", "Cohere", "perplexity"]},
}
TERMINAL = {"submitted", "uncertain", "applying", "submitting"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def fingerprint(job: dict) -> str:
    identity = "|".join(normalized(job.get(k, "")) for k in ("company", "title", "location"))
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


class JobStore:
    def __init__(self, workspace: Path):
        self.root = workspace.resolve() / ".kratos" / "jobs"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "jobs.sqlite3"
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'discovered',
                    score INTEGER NOT NULL, first_seen TEXT NOT NULL, updated_at TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '', receipt TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, outcome TEXT);
                CREATE INDEX IF NOT EXISTS job_application_key ON jobs(json_extract(data,'$.application_key'));
            """)
        self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=15000")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def read(self, key: str, default=None):
        with self.db() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def write(self, key: str, value) -> None:
        with self.db() as db:
            db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))

    def preferences(self) -> dict:
        return {**DEFAULTS, **self.read("preferences", {})}

    def save_preferences(self, changes: dict) -> dict:
        if not isinstance(changes, dict):
            raise ValueError("Preferences must be an object")
        result = self.preferences()
        for key in ("interval_minutes", "daily_limit", "min_score"):
            if key in changes:
                value = changes[key]
                limits = {"interval_minutes": (30, 10080), "daily_limit": (1, 50), "min_score": (0, 100)}[key]
                if isinstance(value, bool) or not isinstance(value, int) or not limits[0] <= value <= limits[1]:
                    raise ValueError(f"{key} must be between {limits[0]} and {limits[1]}")
                result[key] = value
        if "remote_only" in changes:
            if not isinstance(changes["remote_only"], bool):
                raise ValueError("remote_only must be a boolean")
            result["remote_only"] = changes["remote_only"]
        for key in ("locations", "exclude_companies", "keywords", "sources"):
            if key in changes:
                values = changes[key]
                if not isinstance(values, list) or len(values) > 40 or any(not isinstance(v, str) or len(v) > 150 for v in values):
                    raise ValueError(f"Invalid {key}")
                result[key] = [v.strip() for v in values if v.strip()]
        if any(s not in DEFAULTS["sources"] for s in result["sources"]):
            raise ValueError("Unknown job source")
        if "boards" in changes:
            boards = changes["boards"]
            if not isinstance(boards, dict) or set(boards) - {"greenhouse", "lever", "ashby"}:
                raise ValueError("Invalid employer boards")
            for values in boards.values():
                if not isinstance(values, list) or len(values) > 20 or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", v) for v in values):
                    raise ValueError("Use board names, not URLs, with at most 20 per source")
            result["boards"] = {**result["boards"], **boards}
        self.write("preferences", result)
        return result

    def profile(self) -> dict:
        result = self.read("profile", {})
        result.pop("resume_path", None)
        return result

    def resume(self) -> Path | None:
        value = self.read("profile", {}).get("resume_path")
        if not value:
            return None
        path = (self.root / value).resolve()
        if path.parent != (self.root / "documents").resolve() or not path.is_file():
            return None
        return path

    def save_profile(self, changes: dict) -> dict:
        if not isinstance(changes, dict):
            raise ValueError("Applicant profile must be an object")
        result = self.read("profile", {})
        for key in ("name", "email", "phone", "city", "country", "linkedin", "github", "portfolio", "current_company", "summary"):
            if key in changes:
                if not isinstance(changes[key], str) or len(changes[key]) > (8000 if key == "summary" else 400):
                    raise ValueError(f"Invalid {key}")
                result[key] = changes[key].strip()
        if result.get("email") and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result["email"]):
            raise ValueError("Enter a valid applicant email")
        for key in ("linkedin", "github", "portfolio"):
            if result.get(key) and not result[key].startswith("https://"):
                raise ValueError(f"{key} must be an HTTPS URL")
        if "skills" in changes:
            values = changes["skills"]
            if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or len(v) > 80 for v in values):
                raise ValueError("Invalid skills list")
            result["skills"] = [v.strip() for v in values if v.strip()]
        if "years_experience" in changes:
            value = changes["years_experience"]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 60):
                raise ValueError("Invalid years of experience")
            result["years_experience"] = value
        if "answers" in changes:
            answers = changes["answers"]
            if not isinstance(answers, dict) or len(answers) > 150 or any(not isinstance(k, str) or not isinstance(v, (str, bool)) or len(k) > 500 or len(str(v)) > 8000 for k, v in answers.items()):
                raise ValueError("Screening answers must map exact questions to text or booleans")
            result["answers"] = answers
        upload = changes.get("resume")
        if upload:
            if not isinstance(upload, dict):
                raise ValueError("Invalid resume upload")
            suffix = Path(str(upload.get("name", ""))).suffix.lower()
            encoded = upload.get("data", "")
            if suffix not in (".pdf", ".docx", ".txt") or not isinstance(encoded, str) or len(encoded) > 14_000_000:
                raise ValueError("Upload a PDF, DOCX or TXT resume under 10 MB")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except Exception as exc:
                raise ValueError("Invalid resume encoding") from exc
            if not raw or len(raw) > 10_000_000:
                raise ValueError("Resume must be nonempty and under 10 MB")
            if suffix == ".pdf" and not raw.startswith(b"%PDF-"):
                raise ValueError("The uploaded file is not a PDF")
            if suffix == ".docx" and not raw.startswith(b"PK"):
                raise ValueError("The uploaded file is not a DOCX")
            folder = self.root / "documents"
            folder.mkdir(mode=0o700, exist_ok=True)
            name = hashlib.sha256(raw).hexdigest()[:20] + suffix
            path = folder / name
            path.write_bytes(raw)
            path.chmod(0o600)
            result["resume_path"] = "documents/" + name
            result["resume_name"] = Path(str(upload["name"]).replace("\\", "/")).name[:200]
        self.write("profile", result)
        return self.profile()

    def missing_profile(self) -> list[str]:
        profile = self.profile()
        missing = [key for key in ("name", "email", "skills") if not profile.get(key)]
        if not self.resume():
            missing.append("resume")
        return missing

    def upsert(self, job: dict) -> None:
        job = {key: value for key, value in job.items() if key not in {"id", "status", "first_seen", "updated_at", "detail", "receipt"}}
        url = urlsplit(job.get("apply_url") or "")
        query = urlencode([(key, value) for key, value in parse_qsl(url.query) if key.lower() in ("gh_jid", "jobid", "job_id", "postingid", "jk")])
        job["application_key"] = urlunsplit((url.scheme, url.netloc, url.path.rstrip("/"), query, ""))
        job_id = fingerprint(job)
        stamp = now()
        with self.db() as db:
            existing = db.execute("SELECT id,data FROM jobs WHERE id=? OR json_extract(data,'$.application_key')=? LIMIT 1",
                                  (job_id, job["application_key"] or "__no_url__")).fetchone()
            if existing:
                job_id = existing["id"]
                previous = json.loads(existing["data"])
                if previous.get("auto_apply_supported") and not job.get("auto_apply_supported"):
                    for key in ("url", "apply_url", "application_key", "auto_apply_supported", "source", "source_home"):
                        job[key] = previous[key]
            db.execute("""INSERT INTO jobs(id,data,score,first_seen,updated_at) VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET data=excluded.data,score=excluded.score,updated_at=excluded.updated_at""",
                       (job_id, json.dumps(job), job["score"], stamp, stamp))

    @staticmethod
    def _job(row) -> dict:
        result = dict(row)
        result.update(json.loads(result.pop("data")))
        result["receipt"] = json.loads(result["receipt"])
        return result

    def listings(self, limit: int = 500, statuses: tuple[str, ...] = ()) -> list[dict]:
        with self.db() as db:
            where = " WHERE status IN (" + ",".join("?" for _ in statuses) + ")" if statuses else ""
            rows = db.execute("SELECT * FROM jobs" + where + " ORDER BY score DESC,first_seen DESC LIMIT ?", (*statuses, min(limit, 1000))).fetchall()
        return [self._job(row) for row in rows]

    def job(self, job_id: str) -> dict:
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Job not found")
        return self._job(row)

    def set_status(self, job_id: str, status: str, detail: str = "", receipt: dict | None = None) -> None:
        with self.db() as db:
            db.execute("UPDATE jobs SET status=?,detail=?,receipt=?,updated_at=? WHERE id=?",
                       (status, detail[:4000], json.dumps(receipt or {}), now(), job_id))
            if status not in ("applying", "submitting", "queued"):
                db.execute("UPDATE attempts SET finished_at=?,outcome=? WHERE job_id=? AND finished_at IS NULL", (now(), status, job_id))

    def queue(self, job_id: str) -> None:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row[0] in TERMINAL:
                raise ValueError("This job is already submitted, active, or awaiting submission verification")
            db.execute("UPDATE jobs SET status='queued',detail='' WHERE id=?", (job_id,))

    def stop_queued(self) -> None:
        with self.db() as db:
            db.execute("UPDATE jobs SET status='stopped',detail='Stopped before this application began.',updated_at=? WHERE status='queued'", (now(),))

    def claim(self, job_id: str, daily_limit: int) -> bool:
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT COUNT(*) FROM attempts WHERE substr(started_at,1,10)=?", (now()[:10],)).fetchone()[0]
            if count >= daily_limit:
                return False
            changed = db.execute("UPDATE jobs SET status='applying' WHERE id=? AND status='queued'", (job_id,)).rowcount
            if not changed:
                return False
            db.execute("INSERT INTO attempts(job_id,started_at) VALUES (?,?)", (job_id, now()))
        return True

    def recover(self) -> None:
        with self.db() as db:
            db.execute("UPDATE jobs SET status='uncertain',detail='Runtime stopped during an application. Check the employer confirmation before retrying.' WHERE status IN ('applying','submitting')")
            db.execute("UPDATE attempts SET finished_at=?,outcome='uncertain' WHERE finished_at IS NULL", (now(),))

    def counts(self) -> dict:
        minimum = self.preferences()["min_score"]
        with self.db() as db:
            counts = {row[0]: row[1] for row in db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status")}
            counts["attempts_today"] = db.execute("SELECT COUNT(*) FROM attempts WHERE substr(started_at,1,10)=?", (now()[:10],)).fetchone()[0]
            counts["total"] = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            counts["matches"] = db.execute("SELECT COUNT(*) FROM jobs WHERE score>=? AND json_extract(data,'$.eligible')=1", (minimum,)).fetchone()[0]
        return counts
