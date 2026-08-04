"""Standard-library HTTP model service for the API Client."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    reason: str
    body: str
    headers: dict[str, str]
    elapsed_ms: float
    size_bytes: int


def parse_key_values(text: str) -> dict[str, str]:
    """Parse one `Name: value` or `name=value` entry per line."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        separator = ":" if ":" in line else "="
        if separator not in line:
            raise ValueError(f"Invalid entry: {line}")
        key, value = line.split(separator, 1)
        if not key.strip():
            raise ValueError("Parameter names cannot be empty.")
        values[key.strip()] = value.strip()
    return values


def request_api(
    method: str,
    url: str,
    params: Mapping[str, str],
    headers: Mapping[str, str],
    body: str,
    authorization: str,
    credential: str,
) -> HttpResponse:
    """Send a single HTTP request and return a serializable response model."""
    split = urlsplit(url.strip())
    if split.scheme not in {"http", "https"} or not split.netloc:
        raise ValueError("Enter a complete http:// or https:// URL.")
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    query.update(params)
    final_url = urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))
    final_headers = dict(headers)
    if authorization == "Bearer token" and credential.strip():
        final_headers["Authorization"] = f"Bearer {credential.strip()}"
    elif authorization == "Basic auth" and credential.strip():
        encoded = base64.b64encode(credential.encode("utf-8")).decode("ascii")
        final_headers["Authorization"] = f"Basic {encoded}"
    payload = body.encode("utf-8") if body and method not in {"GET", "HEAD"} else None
    if payload and "Content-Type" not in final_headers:
        final_headers["Content-Type"] = "application/json"
    request = Request(final_url, data=payload, headers=final_headers, method=method)
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            response_headers = dict(response.headers.items())
            status, reason = response.status, response.reason
    except HTTPError as error:
        raw = error.read()
        response_headers = dict(error.headers.items()) if error.headers else {}
        status, reason = error.code, str(error.reason)
    except URLError as error:
        raise ValueError(f"Network error: {error.reason}") from error
    encoding = "utf-8"
    content_type = response_headers.get("Content-Type", "")
    if "charset=" in content_type:
        encoding = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
    text = raw.decode(encoding, errors="replace")
    if "json" in content_type.lower():
        try:
            text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            pass
    return HttpResponse(status, reason, text, response_headers, (time.perf_counter() - started) * 1000, len(raw))
