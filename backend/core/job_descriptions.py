"""Collect and retain the available job description without text truncation."""

import json
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup


def plain_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.select("script, style, nav, footer, header, aside, noscript, form"):
        tag.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n", strip=True).splitlines() if line.strip())


def extract_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    if any(marker in title for marker in ("just a moment", "access denied", "verify you are human", "security check", "sign in", "log in")):
        raise ValueError("Listing requires access verification or login.")

    def postings(value):
        if isinstance(value, list):
            for item in value:
                yield from postings(item)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            if types == "JobPosting" or isinstance(types, list) and "JobPosting" in types:
                yield value
            yield from postings(value.get("@graph", []))

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            for posting in postings(json.loads(script.string or script.get_text())):
                description = posting.get("description")
                if isinstance(description, str) and description.strip():
                    return plain_text(description)
        except (ValueError, TypeError):
            continue
    for selector in (".show-more-less-html__markup", '[itemprop="description"]', '[data-testid="job-description"]',
                     '[id*="description"]', '[class*="job-description"]', '[class*="job_description"]',
                     '[class*="job-detail"]', "main", "article", "body"):
        section = soup.select_one(selector)
        if section is not None:
            description = plain_text(str(section))
            if description:
                return description
    return ""


async def fetch_description(url: str) -> str:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "JobForge/1.0", "Accept": "text/html"}) as client:
        response = await client.get(url)
        response.raise_for_status()
        return extract_description(response.text)


def replace_description(job, description: str, source: str) -> bool:
    if not description or len(description.strip()) <= len((job.description or "").strip()):
        return False
    job.description = description
    job.description_source = source
    if job.status == "ranked":
        job.status = "new"
    for field in ("fit_score", "tech_score", "exp_score", "location_score", "growth_score", "strengths", "gaps", "fit_summary", "talking_points", "researched_at"):
        setattr(job, field, None)
    return True


async def ensure_description(job, emit, fetcher=None) -> str:
    if job.portal == "manual":
        job.description_source = "manual"
        return job.description or ""
    now = datetime.utcnow()
    if job.description_checked_at and (not job.description_error or job.description_checked_at > now - timedelta(hours=1)):
        return job.description or ""
    await emit("thinking", f"Checking the available description for {job.title}…")
    try:
        description = await (fetcher or fetch_description)(job.url)
        if not description.strip():
            raise ValueError("No readable job description returned.")
        replace_description(job, description, "listing")
        job.description_error = None
    except (httpx.HTTPError, ValueError) as error:
        job.description_error = str(error)
        await emit("thinking", "Full listing description unavailable; using the stored text.", {"job_id": job.id, "description_warning": job.description_error})
    job.description_checked_at = now
    return job.description or ""
