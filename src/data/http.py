"""Resilient HTTP access with timestamped JSON caching."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


LOGGER = logging.getLogger(__name__)


class DataSourceError(RuntimeError):
    """Raised when a public-data response cannot be used."""


_SECRET_QUERY_PATTERN = re.compile(
    r"(?i)(consumer_key|consumer_secret|accessToken|authKey|serviceKey|apiKey|key)=([^&\s]+)"
)


def redact_secrets(message: str) -> str:
    """Remove credentials that third-party HTTP errors may echo in URLs."""

    return _SECRET_QUERY_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", message)


@dataclass(frozen=True)
class CachedResponse:
    payload: dict[str, Any]
    fetched_at: str
    source: str


class JsonCache:
    """Small auditable cache; every entry records its retrieval time."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in key)
        return self.cache_dir / f"{safe}.json"

    def save(self, key: str, payload: dict[str, Any], source: str) -> CachedResponse:
        item = CachedResponse(
            payload=payload,
            fetched_at=datetime.now(UTC).isoformat(),
            source=source,
        )
        self._path(key).write_text(
            json.dumps(item.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return item

    def load(self, key: str) -> CachedResponse | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return CachedResponse(**raw)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            LOGGER.warning("캐시를 읽을 수 없습니다 (%s): %s", path.name, exc)
            return None


def build_session() -> requests.Session:
    """Return a requests session with bounded retry behavior."""

    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "heatwave-urban-prescription-mvp/1.0"})
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int,
    **kwargs: Any,
) -> dict[str, Any]:
    """Request JSON and turn network/schema failures into a clear domain error."""

    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        safe_error = redact_secrets(str(exc))
        raise DataSourceError(f"공공 API 요청 실패: {url}: {safe_error}") from exc
    except ValueError as exc:
        raise DataSourceError(f"공공 API가 유효한 JSON을 반환하지 않았습니다: {url}") from exc
    if not isinstance(payload, dict):
        raise DataSourceError(f"공공 API JSON 최상위 형식이 객체가 아닙니다: {url}")
    return payload

