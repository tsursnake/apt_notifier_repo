import hashlib
from supabase import create_client, Client
from settings import settings

# SQL migration to run once in Supabase SQL editor:
MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id TEXT UNIQUE NOT NULL,
    url         TEXT NOT NULL,
    price       INT,
    rooms       FLOAT,
    size_m2     INT,
    neighborhood TEXT,
    raw_text    TEXT,
    source      TEXT,
    notified    BOOL NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS listings_notified_idx ON listings (notified);
CREATE INDEX IF NOT EXISTS listings_created_at_idx ON listings (created_at DESC);
"""


def _client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_key)


def external_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def upsert_listing(listing: dict) -> bool:
    """Insert listing; return True if it was newly inserted, False if duplicate."""
    client = _client()
    eid = external_id(listing["url"])
    row = {
        "external_id": eid,
        "url": listing["url"],
        "price": listing.get("price"),
        "rooms": listing.get("rooms"),
        "size_m2": listing.get("size_m2"),
        "neighborhood": listing.get("neighborhood"),
        "raw_text": listing.get("raw_text", ""),
        "source": listing.get("source", ""),
        "notified": False,
    }
    result = (
        client.table("listings")
        .upsert(row, on_conflict="external_id", ignore_duplicates=True)
        .execute()
    )
    # supabase-py returns inserted rows; empty data means conflict → duplicate
    return bool(result.data)


def mark_notified(url: str) -> None:
    client = _client()
    eid = external_id(url)
    client.table("listings").update({"notified": True}).eq("external_id", eid).execute()


if __name__ == "__main__":
    print("=== Supabase migration SQL ===")
    print(MIGRATION_SQL)
