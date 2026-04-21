import logging
import time
import yaml
import os

from scrapers import (
    Yad2Scraper,
    HomelessScraper,
    MadlanScraper,
    WindoScraper,
    KomoScraper,
)
from filters import passes_filters, relevance_score
from notifier import send_notification
from db import upsert_listing, mark_notified

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
logger = logging.getLogger(__name__)

_SCRAPERS = [
    Yad2Scraper,
    HomelessScraper,
    MadlanScraper,
    WindoScraper,
    KomoScraper,
]


def load_config() -> dict:
    path = os.path.join(os.path.dirname(__file__), "config.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_once(cfg: dict) -> None:
    threshold = cfg.get("score_threshold", 50)

    for scraper_cls in _SCRAPERS:
        scraper = scraper_cls()
        logger.info("Running scraper: %s", scraper.source)
        try:
            listings = scraper.fetch()
        except Exception as exc:
            logger.error("Scraper %s crashed: %s", scraper.source, exc)
            listings = []

        logger.info("  %d listings fetched from %s", len(listings), scraper.source)

        for listing in listings:
            try:
                is_new = upsert_listing(listing)
            except Exception as exc:
                logger.error("DB upsert failed for %s: %s", listing.get("url"), exc)
                continue

            if not is_new:
                continue

            if not passes_filters(listing, cfg):
                logger.debug("  Filtered out: %s", listing.get("url"))
                continue

            score = relevance_score(listing, cfg)
            if score < threshold:
                logger.debug(
                    "  Score %d below threshold %d: %s",
                    score,
                    threshold,
                    listing.get("url"),
                )
                continue

            logger.info(
                "  Notifying (score=%d): %s", score, listing.get("url")
            )
            success = send_notification(listing)
            if success:
                try:
                    mark_notified(listing["url"])
                except Exception as exc:
                    logger.error("mark_notified failed: %s", exc)

        # polite delay between scrapers
        if scraper_cls is not _SCRAPERS[-1]:
            scraper.polite_sleep()


def main() -> None:
    logger.info("Apartment notifier starting")
    while True:
        cfg = load_config()
        try:
            run_once(cfg)
        except Exception as exc:
            logger.exception("run_once failed: %s", exc)
        interval = cfg.get("run_interval_seconds", 300)
        logger.info("Sleeping %ds until next run", interval)
        time.sleep(interval)


if __name__ == "__main__":
    main()
