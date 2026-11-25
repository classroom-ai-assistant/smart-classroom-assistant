"""Free photo search through the Pixabay API.

- safesearch=true always: only images "suitable for all ages".
- Search results are cached for 24 h, as Pixabay requires.
- Pixabay forbids permanent hotlinking, so a chosen picture is downloaded
  (through /file) and the browser stores it in the teacher's own files,
  with the author credited.
"""

import logging
import time
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.shared.errors.exceptions import AiFailedError, AiRateLimitedError, NotFoundError

logger = logging.getLogger("app.images")

API = "https://pixabay.com/api/"
CACHE_SECONDS = 24 * 3600
MAX_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png"}


class ImageSearch(Protocol):
    async def search(self, query: str, page: int, image_type: str) -> dict[str, Any]: ...
    async def file(self, image_id: int) -> tuple[bytes, str]: ...


def _allowed_host(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return urlparse(url).scheme == "https" and (host == "pixabay.com" or host.endswith(".pixabay.com"))


class PixabayClient:
    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self._key = api_key
        self._http = http
        self._cache: dict[tuple, tuple[float, dict[str, Any]]] = {}

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        cache_key = tuple(sorted(params.items()))
        hit = self._cache.get(cache_key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            r = await self._http.get(API, params={"key": self._key, "safesearch": "true", **params})
        except httpx.HTTPError as exc:
            logger.warning("pixabay request failed: %s", type(exc).__name__)
            raise AiFailedError("تعذّر البحث عن الصور الآن، حاولي مرة أخرى") from exc
        if r.status_code == 429:
            raise AiRateLimitedError("وصلنا حد البحث عن الصور، حاولي بعد دقيقة")
        if r.status_code != 200:
            logger.warning("pixabay returned HTTP %s", r.status_code)
            raise AiFailedError("تعذّر البحث عن الصور الآن، حاولي مرة أخرى")
        data = r.json()
        if len(self._cache) > 500:
            self._cache.clear()
        self._cache[cache_key] = (time.monotonic(), data)
        return data

    async def search(self, query: str, page: int, image_type: str) -> dict[str, Any]:
        data = await self._get({"q": query, "lang": "ar", "image_type": image_type, "per_page": 24, "page": page})
        items = [
            {
                "id": h["id"],
                "preview_url": h.get("webformatURL") or h.get("previewURL"),
                "width": h.get("webformatWidth") or h.get("previewWidth"),
                "height": h.get("webformatHeight") or h.get("previewHeight"),
                "tags": h.get("tags", ""),
                "author": h.get("user", ""),
                "page_url": h.get("pageURL", ""),
            }
            for h in data.get("hits", [])
        ]
        return {"items": items, "total": int(data.get("totalHits", 0))}

    async def file(self, image_id: int) -> tuple[bytes, str]:
        data = await self._get({"id": image_id})
        hits = data.get("hits") or []
        if not hits:
            raise NotFoundError("الصورة غير موجودة")
        url = hits[0].get("largeImageURL") or hits[0].get("webformatURL") or ""
        if not _allowed_host(url):
            raise AiFailedError("تعذّر تحميل الصورة")
        try:
            r = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise AiFailedError("تعذّر تحميل الصورة، حاولي مرة أخرى") from exc
        content_type = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or content_type not in ALLOWED_TYPES or len(r.content) > MAX_BYTES:
            raise AiFailedError("تعذّر تحميل الصورة، حاولي مرة أخرى")
        return r.content, content_type
