import asyncio
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp
from selectolax.parser import HTMLParser

from config import Target

log = logging.getLogger(__name__)

TIMEOUT = aiohttp.ClientTimeout(total=20)
RETRIES = 3
BASE_DELAY = 2.0  # 2s, 4s, 8s
MAX_DELAY = 300.0  # a hostile Retry-After must not park the loop for a day
RETRY_STATUS = {429, 500, 502, 503, 504}
# ponytail: assumes "1,234.56" formatting; add locale handling when a target uses "1.234,56"
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


class _Retry(Exception):
    """A response worth retrying, carrying the delay the server asked for."""


class ParsingError(Exception):
    """The page loaded but we could not read a price out of it.

    Deliberately outside the retry tuple below: a selector that matches nothing
    is a broken config, and hammering the site three more times will not fix it.
    """


def _to_float(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUMBER.search(str(value))
    if not m:
        raise ValueError(f"no number in {value!r}")
    return float(m.group().replace(",", ""))


def _clp_to_float(text: str) -> float:
    """Visible price text, strictly CLP: "$1.369.990" -> 1369990.0.

    Dots are thousands separators and there are no cents.
    TODO: soporte multidivisa
    """
    m = re.search(r"\d[\d.]*", text)
    if not m:
        raise ParsingError(f"no CLP price in {text!r}")
    return float(m.group().replace(".", ""))


def _from_html(html: str, target: Target) -> float:
    node = HTMLParser(html).css_first(target.css_selector)
    if node is None:
        raise ParsingError(f"selector {target.css_selector!r} matched nothing")
    if not target.css_attribute:
        return _clp_to_float(node.text())
    value = node.attributes.get(target.css_attribute)
    if value is None:
        raise ParsingError(f"node has no attribute {target.css_attribute!r}")
    return _to_float(value)


async def _json(r: aiohttp.ClientResponse, target: Target) -> Any:
    """Decode a JSON body, or say plainly that this target is misconfigured."""
    try:
        return await r.json(content_type=None)
    except ValueError:  # JSONDecodeError; the body is HTML, or an error page
        body = " ".join((await r.text())[:80].split())
        raise ParsingError(
            f"{target.url} did not return JSON (got {body!r}...); "
            "use css_selector instead of json_path"
        ) from None


def _dig(data: Any, path: str) -> Any:
    """Walk a dotted path; digit segments index into lists ("items.0.price")."""
    for key in path.split("."):
        data = data[int(key)] if key.isdigit() else data[key]
    return data


def _retry_after(response: aiohttp.ClientResponse) -> float | None:
    """Seconds requested by a Retry-After header, in either legal form."""
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return float(raw)
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


async def fetch_price(session: aiohttp.ClientSession, target: Target) -> float:
    """Fetch one price, retrying timeouts, 429 and 5xx with exponential backoff.

    A 429 that carries Retry-After waits exactly that long instead. 4xx other
    than 429 raises immediately -- retrying a 404 does not make it exist, and
    neither does retrying a ParsingError.
    """
    for attempt in range(RETRIES + 1):
        delay = BASE_DELAY * 2**attempt
        try:
            async with session.get(target.url, timeout=TIMEOUT) as r:
                if r.status in RETRY_STATUS:
                    delay = min(_retry_after(r) or delay, MAX_DELAY)
                    raise _Retry(f"HTTP {r.status}")
                r.raise_for_status()
                if target.css_selector:
                    return _from_html(await r.text(), target)
                return _to_float(_dig(await _json(r, target), target.json_path))
        except (_Retry, aiohttp.ClientError, asyncio.TimeoutError) as e:
            if isinstance(e, aiohttp.ClientResponseError) or attempt == RETRIES:
                raise
            log.warning(
                "%s: %s, retry %d/%d in %.0fs", target.name, e or type(e).__name__,
                attempt + 1, RETRIES, delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")
