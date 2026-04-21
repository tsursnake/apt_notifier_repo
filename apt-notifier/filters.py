import re
from typing import Any

_EXCLUDE_PATTERNS = re.compile(
    r"שותף|שותפת|שותפים|סאבלט|roommate|sublet|חדר", re.IGNORECASE
)


def _load_config() -> dict:
    import yaml, os
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def passes_filters(listing: dict, cfg: dict | None = None) -> bool:
    if cfg is None:
        cfg = _load_config()

    raw = (listing.get("raw_text") or "").lower()
    if _EXCLUDE_PATTERNS.search(raw):
        return False

    price = listing.get("price")
    if price is not None:
        if cfg.get("price_min") and price < cfg["price_min"]:
            return False
        if cfg.get("price_max") and price > cfg["price_max"]:
            return False

    rooms = listing.get("rooms")
    if rooms is not None:
        if cfg.get("rooms_min") and rooms < cfg["rooms_min"]:
            return False
        if cfg.get("rooms_max") and rooms > cfg["rooms_max"]:
            return False

    neighborhoods: list[str] = cfg.get("neighborhoods") or []
    if neighborhoods:
        nbhood = (listing.get("neighborhood") or "").strip()
        if nbhood and not any(n in nbhood for n in neighborhoods):
            return False

    return True


def relevance_score(listing: dict, cfg: dict | None = None) -> int:
    if cfg is None:
        cfg = _load_config()

    score = 50  # baseline

    price = listing.get("price")
    if price is not None:
        mid = (cfg.get("price_min", 5000) + cfg.get("price_max", 9000)) / 2
        deviation = abs(price - mid) / max(mid, 1)
        score += max(0, 20 - int(deviation * 40))
    else:
        score -= 10

    if listing.get("rooms") is not None:
        score += 10

    if listing.get("size_m2") is not None:
        score += 10

    if listing.get("neighborhood"):
        score += 10

    neighborhoods: list[str] = cfg.get("neighborhoods") or []
    if neighborhoods and listing.get("neighborhood"):
        if any(n in (listing["neighborhood"] or "") for n in neighborhoods):
            score += 20

    return min(max(score, 0), 100)
