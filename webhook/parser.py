import json
import re
import logging
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

_client = AsyncAnthropic(timeout=8.0)

_SYSTEM = """You are a real estate listing parser for Israeli apartments in Tel Aviv.
Extract apartment listings from the text. For each listing return a JSON array:
[{
  "price": int or null,
  "rooms": float or null,
  "neighborhood": string or null,
  "size_m2": int or null,
  "url": string or null,
  "raw": string,
  "exclude": bool (true if contains שותף/שותפת/שותפים/סאבלט/roommate/sublet)
}]
Return ONLY valid JSON array, no markdown, no preamble."""


async def parse_listings(text: str) -> list[dict]:
    logger.info("Haiku input (%d chars): %s", len(text), text[:300])
    response = await _client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": text}],
    )
    raw = response.content[0].text.strip()
    logger.info("Haiku raw response: %s", raw[:1000])
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    listings = json.loads(raw)
    for i, listing in enumerate(listings):
        logger.info("Parsed listing[%d]: %s", i, listing)
    return listings
