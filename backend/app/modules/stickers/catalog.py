"""Sticker library: a curated, kid-friendly subset of Microsoft Fluent Emoji
(3D style, MIT licence). Files are served from the jsDelivr CDN pinned to one
commit, so the pictures never change under a saved lesson."""

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

FLUENT_COMMIT = "1ffb34c752ecf5d402f04cfb4b392c77f57c54bc"
CDN = f"https://cdn.jsdelivr.net/gh/microsoft/fluentui-emoji@{FLUENT_COMMIT}/"
CREDIT = "Fluent Emoji © Microsoft — MIT License"

CATEGORIES = {
    "animals": "حيوانات",
    "food": "فواكه وأكل",
    "nature": "طبيعة وطقس",
    "school": "مدرسة وألعاب",
    "transport": "مواصلات",
    "shapes": "أشكال وألوان",
    "numbers": "أرقام",
    "feelings": "مشاعر وتشجيع",
}


@lru_cache(maxsize=1)
def catalog() -> list[dict[str, str]]:
    rows = json.loads((Path(__file__).parent / "catalog.json").read_text(encoding="utf-8"))
    return [{**r, "url": CDN + quote(r["path"])} for r in rows]


@lru_cache(maxsize=1)
def names() -> frozenset[str]:
    return frozenset(r["name"] for r in catalog())
