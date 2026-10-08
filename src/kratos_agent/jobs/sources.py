from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Event
from urllib.parse import urlsplit, urlunsplit

import requests

from .store import normalized

SOURCE_LINKS = {
    "remoteok": "https://remoteok.com", "arbeitnow": "https://www.arbeitnow.com",
    "greenhouse": "https://www.greenhouse.com", "lever": "https://www.lever.co",
    "ashby": "https://www.ashbyhq.com",
}
AI_ROLE = re.compile(r"\b(ai|ml|llm|nlp|mlops|artificial intelligence|machine learning|deep learning|computer vision|data scientist|research scientist|applied scientist|generative ai|prompt engineer|reinforcement learning)\b", re.I)
ATS_HOSTS = {"jobs.lever.co", "jobs.eu.lever.co", "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.ashbyhq.com"}
AI_TECH = re.compile(r"\b(machine learning|deep learning|llms?|large language models?|nlp|computer vision|mlops|generative ai|reinforcement learning|neural networks?)\b", re.I)


def ai_role(job: dict) -> bool:
    title = job["title"]
    if AI_ROLE.search(title):
        if re.search(r"\b(research scientist|applied scientist)\b", title, re.I) and not AI_TECH.search(title + " " + job["description"]):
            return False
        return True
    return bool(re.search(r"\b(engineer|research|scientist|technical staff|developer)\b", title, re.I) and AI_TECH.search(job["description"]))


def plain(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", html.unescape(str(value or "")))).strip()[:30000]


def clean_url(value: str) -> str:
    try:
        url = urlsplit(str(value))
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.port not in (None, 443):
            return ""
        return urlunsplit(("https", url.netloc, url.path, url.query, ""))
    except ValueError:
        return ""


def supported_url(value: str) -> bool:
    return bool(clean_url(value)) and urlsplit(value).hostname in ATS_HOSTS


def listing(source: str, **values) -> dict:
    result = {"source": source, "source_home": SOURCE_LINKS[source], "title": "", "company": "", "location": "",
              "description": "", "url": "", "apply_url": "", "remote": False, "published_at": "", "salary": "", **values}
    result["description"] = plain(result["description"])
    result["title"] = plain(result["title"])[:300]
    result["company"] = plain(result["company"])[:200]
    result["location"] = plain(result["location"])[:300]
    result["url"] = clean_url(result["url"])
    result["apply_url"] = clean_url(result["apply_url"]) or result["url"]
    result["auto_apply_supported"] = supported_url(result["apply_url"])
    return result


def matching(job: dict, profile: dict, preferences: dict) -> dict:
    title = normalized(job["title"])
    text = normalized(job["title"] + " " + job["description"])
    skills = [skill for skill in profile.get("skills", []) if f" {normalized(skill)} " in f" {text} "]
    reasons = []
    if preferences["remote_only"] and not job["remote"]:
        reasons.append("This role is not marked remote")
    if preferences["locations"] and not any(normalized(loc) in normalized(job["location"]) for loc in preferences["locations"]):
        reasons.append("Location does not match your filters; remote can still have regional restrictions")
    if any(normalized(company) in normalized(job["company"]) for company in preferences["exclude_companies"]):
        reasons.append("Company is excluded")
    if preferences["keywords"] and not any(normalized(word) in text for word in preferences["keywords"]):
        reasons.append("Preferred role keywords do not match")
    years = profile.get("years_experience")
    requirements = re.findall(r"\b(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*years? (?:of )?(?:professional |relevant |industry )?experience", job["description"], re.I)
    if years is not None and requirements and years < max(map(int, requirements)):
        reasons.append("Listed experience requirement exceeds your profile")
    if profile.get("skills") and not skills:
        reasons.append("No supplied skill matches this listing")
    score = 55 + min(len(skills) * 8, 30) + (5 if job["remote"] else 0) + (5 if re.search(r"\b(engineer|scientist|research|developer)\b", title) else 0)
    published = str(job.get("published_at") or "")
    try:
        timestamp = datetime.fromtimestamp(float(published), timezone.utc) if published.replace(".", "", 1).isdigit() else datetime.fromisoformat(published.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).days
        if age <= 14:
            score += 5
        if age > 60:
            reasons.append("Posting is older than 60 days")
    except (ValueError, OverflowError, OSError):
        pass
    return {**job, "score": min(score, 100), "matched_skills": skills, "match_reasons": reasons, "eligible": not reasons}


def fetch_json(url: str, stop: Event):
    for attempt in range(2):
        if stop.is_set():
            raise InterruptedError("Stopped")
        try:
            with requests.get(url, headers={"User-Agent": "KratosJobs/1.0 (public job discovery)", "Accept": "application/json"},
                              timeout=(5, 20), stream=True, allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("The feed did not return a job list")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    if stop.is_set():
                        raise InterruptedError("Stopped")
                    size += len(chunk)
                    if size > 20_000_000:
                        raise ValueError("Job feed exceeded 20 MB")
                    chunks.append(chunk)
                import json
                return json.loads(b"".join(chunks))
        except (requests.RequestException, ValueError):
            if attempt or stop.wait(2):
                raise


def collect_source(source: str, board: str, stop: Event) -> list[dict]:
    if source == "remoteok":
        data = fetch_json("https://remoteok.com/api", stop)
        return [listing(source, title=j.get("position", ""), company=j.get("company", ""), location=j.get("location", "Remote"),
                        description=j.get("description", ""), url=j.get("url", ""), apply_url=j.get("apply_url", ""),
                        remote=True, published_at=j.get("epoch", ""), salary=f"{j.get('salary_min') or ''}–{j.get('salary_max') or ''}")
                for j in data if isinstance(j, dict) and j.get("position")]
    if source == "arbeitnow":
        data = fetch_json("https://www.arbeitnow.com/api/job-board-api", stop)
        return [listing(source, title=j["title"], company=j.get("company_name", ""), location=j.get("location", ""),
                        description=j.get("description", ""), url=j.get("url", ""), remote=bool(j.get("remote")), published_at=j.get("created_at", ""))
                for j in data.get("data", []) if j.get("title")]
    if source == "greenhouse":
        data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", stop)
        return [listing(source, title=j["title"], company=board, location=j.get("location", {}).get("name", ""),
                        description=j.get("content", ""), url=j.get("absolute_url", ""),
                        remote="remote" in j.get("location", {}).get("name", "").lower(), published_at=j.get("updated_at", ""))
                for j in data.get("jobs", []) if j.get("title")]
    if source == "lever":
        data = fetch_json(f"https://api.lever.co/v0/postings/{board}?mode=json&limit=250", stop)
        return [listing(source, title=j["text"], company=board, location=j.get("categories", {}).get("location", ""),
                        description=(j.get("descriptionPlain") or "") + " " + " ".join(plain(v.get("content", "")) for v in (j.get("lists") or [])),
                        url=j.get("hostedUrl", ""), apply_url=j.get("applyUrl", ""),
                        remote=j.get("workplaceType") == "remote", published_at=(j.get("createdAt") or 0) / 1000)
                for j in data if j.get("text")]
    if source == "ashby":
        data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true", stop)
        return [listing(source, title=j["title"], company=board, location=j.get("location", ""),
                        description=j.get("descriptionPlain") or j.get("descriptionHtml", ""), url=j.get("jobUrl", ""),
                        apply_url=j.get("applyUrl", ""), remote=bool(j.get("isRemote")), published_at=j.get("publishedAt", ""),
                        salary=(j.get("compensation") or {}).get("scrapeableCompensationSalarySummary", ""))
                for j in data.get("jobs", []) if j.get("title") and j.get("isListed", True)]
    return []


def discover(preferences: dict, profile: dict, stop: Event) -> tuple[list[dict], list[dict]]:
    jobs, reports = [], []
    requests_to_make = [(source, "") for source in preferences["sources"] if source in ("remoteok", "arbeitnow")]
    requests_to_make += [(source, board) for source in preferences["sources"] if source in ("greenhouse", "lever", "ashby")
                         for board in preferences["boards"].get(source, [])]
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="kratos-job-source") as pool:
        futures = {pool.submit(collect_source, source, board, stop): (source, board) for source, board in requests_to_make}
        for future in as_completed(futures):
            source, board = futures[future]
            try:
                found = future.result()
                relevant = [matching(job, profile, preferences) for job in found if ai_role(job) and job["url"]]
                jobs.extend(relevant)
                reports.append({"source": source, "board": board, "count": len(relevant), "status": "ok"})
            except Exception as exc:
                reports.append({"source": source, "board": board, "count": 0, "status": "error", "error": str(exc)[:300]})
    return jobs, reports
