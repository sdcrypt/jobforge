"""Pace portal requests, reuse responses, and remember access failures."""

import asyncio
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
import structlog
from bs4 import BeautifulSoup
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from core import database
from core.config import settings
from models.portal_request import PortalRequestState

log = structlog.get_logger()

PORTALS = {
    "linkedin.com": ("linkedin", "LinkedIn"),
    "jobleads.com": ("jobleads", "JobLeads"),
    "remoteok.com": ("remoteok", "RemoteOK"),
    "weworkremotely.com": ("weworkremotely", "We Work Remotely"),
    "hn.algolia.com": ("hackernews", "Hacker News"),
}
portal_session = ContextVar("portal_session", default=None)


def portal_for(url):
    """Treat a portal's country subdomains as the same request destination."""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    for domain, (portal, label) in PORTALS.items():
        if host == domain or host.endswith("." + domain):
            return domain, portal, label
    return host, host, host


def retry_time(value, now):
    """Read Retry-After as seconds or an HTTP date; use 15 minutes if absent."""
    try:
        if value is not None and str(value).strip().isdigit():
            return now + timedelta(seconds=max(1, int(value)))
        parsed = parsedate_to_datetime(value)
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return max(now + timedelta(seconds=1), parsed)
    except (ValueError, TypeError, OverflowError, AttributeError):
        return now + timedelta(seconds=settings.portal_rate_limit_cooldown_seconds)


class PortalUnavailable(RuntimeError):
    """An access failure that must not trigger more requests to this portal."""

    def __init__(self, label, failure_type, until):
        self.failure_type = failure_type
        self.until = until
        reason = "rate limited requests (HTTP 429)" if failure_type == "rate_limited" else "denied automated access (HTTP 403 or verification page)"
        super().__init__(f"{label} {reason}. Further requests skipped; try again after {until:%Y-%m-%d %H:%M:%S} UTC.")


class RequestPolicy:
    """Allow one request per host at a time, including across Celery processes.

    Live runs use a short database lease. Standalone parser tests can use local
    state. A crashed worker's lease expires, while its cooldown stays saved.
    """

    def __init__(self, persistent=False, now=None, sleep=None):
        self.persistent = persistent
        self.now = now or datetime.utcnow
        self.sleep = sleep or asyncio.sleep
        self.local = {}

    async def reserve(self, host, label):
        while True:
            now = self.now()
            if self.persistent:
                async with database.AsyncSessionLocal() as db:
                    state = (await db.execute(select(PortalRequestState).where(
                        PortalRequestState.host == host).with_for_update())).scalar_one_or_none()
                    if state is None:
                        try:
                            async with db.begin_nested():
                                state = PortalRequestState(host=host)
                                db.add(state)
                                await db.flush()
                        except IntegrityError:
                            state = (await db.execute(select(PortalRequestState).where(
                                PortalRequestState.host == host).with_for_update())).scalar_one()
                    owner, delay, values = self._reserve(state, host, label, now)
                    if owner:
                        # One conditional update also protects SQLite, which does
                        # not support SELECT FOR UPDATE row locks.
                        claimed = await db.execute(update(PortalRequestState).where(
                            PortalRequestState.host == host,
                            (PortalRequestState.owner == None) | (PortalRequestState.lease_until <= now),
                            (PortalRequestState.next_request_at == None) | (PortalRequestState.next_request_at <= now),
                            (PortalRequestState.cooldown_until == None) | (PortalRequestState.cooldown_until <= now),
                        ).values(**values))
                        if not claimed.rowcount:
                            owner, delay = None, 0.5
                    await db.commit()
            else:
                state = self.local.setdefault(host, PortalRequestState(host=host))
                owner, delay, values = self._reserve(state, host, label, now)
                for key, value in values.items():
                    setattr(state, key, value)
            if owner:
                return owner
            await self.sleep(delay)

    def _reserve(self, state, host, label, now):
        if state.cooldown_until and state.cooldown_until > now:
            raise PortalUnavailable(label, state.failure_type, state.cooldown_until)
        if state.owner and state.lease_until and state.lease_until > now:
            return None, 0.5, {}
        if state.next_request_at and state.next_request_at > now:
            return None, min(1, (state.next_request_at - now).total_seconds()), {}
        owner = str(uuid.uuid4())
        spacing = settings.portal_request_interval_seconds
        if host in ("linkedin.com", "jobleads.com"):
            spacing = settings.portal_sensitive_request_interval_seconds
        return owner, 0, {"owner": owner, "lease_until": now + timedelta(seconds=60),
                          "next_request_at": now + timedelta(seconds=spacing)}

    async def release(self, host, owner, failure=None):
        """Release only our lease, and save any cooldown before another request starts."""
        values = {"owner": None, "lease_until": None}
        if failure:
            values.update(cooldown_until=failure.until, failure_type=failure.failure_type)
        if self.persistent:
            async with database.AsyncSessionLocal() as db:
                await db.execute(update(PortalRequestState).where(
                    PortalRequestState.host == host, PortalRequestState.owner == owner).values(**values))
                await db.commit()
        else:
            state = self.local[host]
            if state.owner == owner:
                for key, value in values.items():
                    setattr(state, key, value)


class PortalHTTP:
    """Share this client across one search run, including nested portal agents."""

    def __init__(self, emit=None, persistent=False, policy=None, transport=None):
        self.emit = emit
        self.policy = policy or RequestPolicy(persistent=persistent)
        self.transport = transport
        self.cache = {}
        self.blocked = {}
        self.announced = set()

    async def get(self, url, params=None, headers=None):
        key = str(httpx.URL(url, params=params))
        if key in self.cache:
            return self.cache[key]
        host, portal, label = portal_for(url)
        if host in self.blocked:
            raise self.blocked[host]
        owner = None
        failure = None
        response = None
        try:
            owner = await self.policy.reserve(host, label)
            # The total timeout stays shorter than the lease, including redirects.
            async with asyncio.timeout(25):
                async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                             headers=headers, transport=self.transport) as client:
                    response = await client.get(url, params=params)
            if response.status_code == 429:
                failure = PortalUnavailable(label, "rate_limited", retry_time(response.headers.get("Retry-After"), self.policy.now()))
            elif response.status_code in (401, 403):
                failure = PortalUnavailable(label, "access_denied", self.policy.now() + timedelta(seconds=settings.portal_access_denied_cooldown_seconds))
            elif response.status_code == 200:
                title = None if response.text.lstrip().startswith(("[", "{")) else BeautifulSoup(response.text, "html.parser").title
                title_text = title.get_text(" ", strip=True).lower() if title else ""
                if any(marker in title_text for marker in ("just a moment", "access denied", "verify you are human", "security check", "sign in", "log in")):
                    failure = PortalUnavailable(label, "access_denied", self.policy.now() + timedelta(seconds=settings.portal_access_denied_cooldown_seconds))
            if failure:
                raise failure
            if response.status_code != 200:
                response.raise_for_status()
            if not response.text.strip():
                raise ValueError(f"{label} returned an empty response.")
            self.cache[key] = response
            return response
        except PortalUnavailable as error:
            failure = error
            # Save the cooldown before publishing an event or releasing the host
            # to another process. Notification failures cannot lose this state.
            if owner:
                await self.policy.release(host, owner, failure)
                owner = None
            self.blocked[host] = error
            if host not in self.announced:
                self.announced.add(host)
                log.warning("search.http_error", portal=portal, url=url,
                            status=response.status_code if response is not None else None,
                            failure_type=error.failure_type, retry_at=error.until.isoformat() + "Z")
                if self.emit:
                    await self.emit("error", str(error), {"portal": portal, "url": url,
                        "failure_type": error.failure_type, "retry_at": error.until.isoformat() + "Z"})
            raise
        finally:
            if owner:
                await self.policy.release(host, owner, failure)


def raise_if_all_portals_failed(reports):
    """Do not retry an entire pipeline immediately when every portal is blocked."""
    if reports and all(report["status"] == "failed" for report in reports.values()):
        message = "All configured portals failed. See portal reports for details."
        if all(report.get("failure_type") in ("rate_limited", "access_denied") for report in reports.values()):
            raise ValueError(message + " Wait for the portal cooldowns before starting a new run.")
        raise RuntimeError(message)
