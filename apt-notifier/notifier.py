import asyncio
import logging
from telegram import Bot
from telegram.error import TelegramError
from settings import settings

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=settings.telegram_bot_token)
    return _bot


def _format_message(listing: dict) -> str:
    neighborhood = listing.get("neighborhood") or "תל אביב"
    rooms = listing.get("rooms")
    price = listing.get("price")
    size_m2 = listing.get("size_m2")
    source = listing.get("source", "")
    url = listing.get("url", "")

    rooms_str = str(rooms) if rooms is not None else "?"
    price_str = f"{price:,}" if price is not None else "?"
    size_str = f"{size_m2}m²" if size_m2 is not None else "?"

    return (
        f"🏠 {neighborhood} – {rooms_str} חד׳ – {price_str}₪\n"
        f"📐 {size_str} | {source}\n"
        f"🔗 {url}"
    )


def send_notification(listing: dict) -> bool:
    message = _format_message(listing)
    try:
        asyncio.run(_send(message))
        return True
    except TelegramError as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


async def _send(text: str) -> None:
    bot = _get_bot()
    await bot.send_message(
        chat_id=settings.telegram_chat_id,
        text=text,
        disable_web_page_preview=False,
    )
