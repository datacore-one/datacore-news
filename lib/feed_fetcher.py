#!/usr/bin/env python3
"""
RSS Feed Fetcher for News Module
Fetches and parses RSS feeds, stores headlines for scoring.

Usage:
    python feed_fetcher.py              # Fetch all enabled feeds
    python feed_fetcher.py --json       # JSON output
    python feed_fetcher.py --dry-run    # Show what would be fetched
"""

import os
import sys
import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# feedparser lives in .datacore/venv — system python is PEP-668 managed and
# cannot host it. Callers invoke this as a bare `python3`, so put the venv on
# sys.path before importing. No-op under the venv interpreter itself.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
try:
    import venv_bootstrap

    venv_bootstrap.activate()
except ImportError:
    pass

# Try to import feedparser, provide helpful error if missing
try:
    import feedparser
except ImportError:
    print(
        "Error: feedparser not installed. Run: "
        ".datacore/venv/bin/pip install -r .datacore/lib/requirements.txt"
    )
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)

# Siblings, imported by path because this script is run directly as well as
# imported (the venv bootstrap above owns sys.path for third-party packages).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import news_paths
news_paths.ensure_core_lib()
import news_scorer
from news_store import NewsStore
# Core helpers: bounded reads, locked atomic writes, public-only downloads.
from module_context import parse_json, read_text
from file_utils import atomic_write_json, file_lock
from public_download import download
from yaml_safety import UniqueStringKeyLoader

MAX_FEED_BYTES = 4 * 1024**2
MAX_PROCESSED_IDS = 2000
STORE_MAX_ITEMS = 500

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Module paths. User data lives in the space's private module-data folder
# (news_paths, MEM-63); it is bound on first use, not at import, so importing
# this module never touches a store.
MODULE_DIR = Path(__file__).parent.parent
FEEDS_EXAMPLE = news_paths.EXAMPLES_DIR / "feeds.example.yaml"
DATA_DIR = None
FEEDS_FILE = None
HEADLINES_FILE = None
PROCESSED_FILE = None


def _bind_paths():
    """Resolve the private data folder once; explicit (test) bindings win."""
    global DATA_DIR, FEEDS_FILE, HEADLINES_FILE, PROCESSED_FILE
    if DATA_DIR is None:
        DATA_DIR = news_paths.data_dir()
    FEEDS_FILE = FEEDS_FILE or DATA_DIR / "feeds.local.yaml"
    HEADLINES_FILE = HEADLINES_FILE or DATA_DIR / "headlines.json"
    PROCESSED_FILE = PROCESSED_FILE or DATA_DIR / ".processed_items.json"


def load_feeds_config() -> dict:
    """Load feeds configuration from YAML file."""
    _bind_paths()
    config_file = FEEDS_FILE if FEEDS_FILE.exists() else FEEDS_EXAMPLE

    if not config_file.exists():
        logger.error(f"No feeds config found. Create {FEEDS_FILE}")
        return {"feeds": []}

    raw = read_text(config_file.parent, config_file, limit=1024**2)
    config = (yaml.load(raw, Loader=UniqueStringKeyLoader) if raw else None) or {}
    if (not isinstance(config, dict) or not isinstance(config.get('feeds', []), list)
            or any(not isinstance(feed, dict) for feed in config.get('feeds', []))):
        raise ValueError(f'invalid news feed configuration in {config_file.name}')

    logger.info(f"Loaded {len(config.get('feeds', []))} feeds from {config_file.name}")
    return config


def _read_processed_ids() -> list:
    """The acknowledged identities, oldest first. A corrupt ledger raises
    rather than reading as empty: resetting it would re-acknowledge nothing
    and hide the damage (the original file is left untouched)."""
    _bind_paths()
    if not PROCESSED_FILE.parent.exists():
        return []
    raw = read_text(PROCESSED_FILE.parent, PROCESSED_FILE)
    if raw is None:
        return []
    data = parse_json(raw)
    if (not isinstance(data, dict) or not isinstance(data.get('processed_ids'), list)
            or any(not isinstance(item, str) or not item for item in data['processed_ids'])):
        raise ValueError('invalid processed news identities; original preserved')
    return data['processed_ids']


def load_processed_items() -> set:
    """Load set of already processed item IDs."""
    return set(_read_processed_ids())


def save_processed_items(processed_ids: set):
    """Acknowledge fetched identities.

    Merges with the ledger on disk under its lock, so a concurrent fetcher's
    acknowledgements are kept, then keeps the newest MAX_PROCESSED_IDS to
    prevent unbounded growth. An identity that ages out of the ledger cannot
    duplicate a stored item: NewsStore.add_items is idempotent by id and link.
    """
    if any(not isinstance(item, str) or not item for item in processed_ids):
        raise ValueError('invalid processed news identities')
    _bind_paths()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with file_lock(PROCESSED_FILE):
        existing = _read_processed_ids()
        known = set(existing)
        combined = existing + sorted(i for i in processed_ids if i not in known)
        atomic_write_json(PROCESSED_FILE, {
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'processed_ids': combined[-MAX_PROCESSED_IDS:],
        })


def generate_item_id(item: dict, feed_name: str) -> str:
    """Generate unique ID for a feed item."""
    # Use link as primary ID, fallback to title+date hash
    link = item.get('link', '')
    if link:
        return hashlib.sha256(link.encode()).hexdigest()

    title = item.get('title', '')
    date = item.get('published', item.get('updated', ''))
    content = f"{feed_name}:{title}:{date}"
    return hashlib.sha256(content.encode()).hexdigest()


def parse_feed(feed_config: dict) -> list:
    """Parse a single RSS feed and return items."""
    name = feed_config.get('name', 'Unknown')
    url = feed_config.get('url', '')
    category = feed_config.get('category', 'general')
    enabled = feed_config.get('enabled', True)

    if not enabled:
        logger.debug(f"Skipping disabled feed: {name}")
        return []

    if not url:
        logger.warning(f"No URL for feed: {name}")
        return []

    logger.info(f"Fetching: {name}")

    try:
        # Bounded, public-only download (no file:// or local services), then
        # the real parser over the bytes.
        feed = feedparser.parse(download(url, max_bytes=MAX_FEED_BYTES))

        if feed.bozo and feed.bozo_exception:
            logger.warning(f"Feed parse warning for {name}: {feed.bozo_exception}")

        items = []
        for entry in feed.entries[:20]:  # Limit to 20 most recent
            # Parse published date
            published = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)

            item = {
                'id': generate_item_id(entry, name),
                'title': entry.get('title', 'No title'),
                'link': entry.get('link', ''),
                'published': published.isoformat() if published else None,
                'summary': entry.get('summary', '')[:500],  # Truncate long summaries
                'source': name,
                'category': category,
                'fetched_at': datetime.now(timezone.utc).isoformat(),
            }
            items.append(item)

        logger.info(f"  Found {len(items)} items from {name}")
        return items

    except Exception:
        raise ValueError(f'news feed retrieval or parsing failed: {name}') from None


def fetch_all_feeds(config: dict, processed_ids: set) -> list:
    """Fetch all enabled feeds and return new items."""
    feeds = config.get('feeds', [])
    all_items = []

    for feed_config in feeds:
        # One unreachable feed must not cost the others their fetch.
        try:
            items = parse_feed(feed_config)
        except ValueError as e:
            logger.error(str(e))
            continue

        # Filter out already processed items
        new_items = [item for item in items if item['id'] not in processed_ids]

        if len(items) > len(new_items):
            logger.debug(f"  Skipped {len(items) - len(new_items)} already processed items")

        all_items.extend(new_items)

    # Sort by published date (newest first)
    all_items.sort(
        key=lambda x: x.get('published') or '0',
        reverse=True
    )

    return all_items


def _store() -> NewsStore:
    _bind_paths()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return NewsStore(HEADLINES_FILE)


def load_headlines() -> dict:
    """Load existing headlines (a fresh read; malformed state raises)."""
    return _store()._load()


def save_headlines(headlines: dict):
    """Merge additions while preserving existing scores and annotations."""
    NewsStore._validate(headlines)
    return _store().add_items(headlines['items'])


def score_unscored_items(store: Optional[NewsStore] = None) -> dict:
    """Score every unscored item in the store and persist the result.

    Runs at fetch time rather than as a separate pass because the store keeps
    only the newest 500 items -- roughly four days at current feed volume -- so
    anything not scored now ages out unscored. That is what happened until
    2026-09-21: the rules existed only as prose for an agent to run by hand,
    nothing scheduled it, and the store held 500 items with 0 scored.

    No cap on how many are scored, for the same reason.
    """
    store = store or NewsStore()
    sources = news_scorer.load_relevance_sources()
    high, medium = news_scorer.load_thresholds()

    scores = {}
    for item in store.get_unscored_items():
        scores[item['id']] = news_scorer.score_item(item, sources, high, medium)
    # One locked mutation for the whole pass: a concurrent writer's items and
    # scores survive, and an item another pass scored meanwhile is left alone.
    scored = store.update_scores(scores)

    return {'status': 'success', 'scored': scored, 'stats': store.get_stats()}


def fetch_and_store(dry_run: bool = False) -> dict:
    """Fetch feeds and store new items."""
    _bind_paths()
    config = load_feeds_config()
    processed_ids = load_processed_items()

    # Fetch new items
    new_items = fetch_all_feeds(config, processed_ids)

    if dry_run:
        return {
            'status': 'dry_run',
            'new_items_count': len(new_items),
            'items': new_items
        }

    # `apply_keyword_boost` lived here and wrote `keyword_modifier` onto every
    # item. It was a SECOND keyword rule that disagreed with the documented one
    # in commands/news.md — it demoted by 15 where the spec says 10, and it
    # matched raw substrings, so "fed" hit "federal" and any keyword appearing
    # inside an HTML attribute scored. Nothing ever read the field it wrote.
    # Removed 2026-09-21 when scoring became real: news_scorer.py now applies
    # the documented rules, once, on word boundaries.
    category_weights = config.get('category_weights', {})
    for item in new_items:
        category = item.get('category', 'general')
        item['category_weight'] = category_weights.get(category, 0.5)

        # Mark as unscored
        item['relevance_score'] = None
        item['tier'] = None

    # Merge under the store lock: a repeated feed entry cannot reset a scored
    # item, and concurrent writers keep each other's additions and scores.
    store = _store()
    additions = {}
    for item in new_items:
        additions.setdefault(item['id'], item)
    added = store.add_items(list(additions.values()))

    # Keep the newest STORE_MAX_ITEMS. Items over the cap are archived beside
    # the store before it is published without them -- never silently dropped.
    store.cleanup_old_items(max_age_days=None, max_items=STORE_MAX_ITEMS)
    stats = store.get_stats()

    # Scoring must never cost us the fetch: the items are on disk above and stay
    # scorable on the next run, so a scorer fault is logged and nothing else.
    try:
        scoring = score_unscored_items(store)
        stats = scoring['stats']
    except Exception as e:
        logger.error(f"Scoring pass failed, items left unscored: {e}")
        scoring = {'status': 'error', 'error': str(e), 'scored': 0}

    # Publication precedes fetch-history acknowledgement. A crash here retries
    # idempotently against the retained authoritative items.
    save_processed_items({item['id'] for item in new_items})

    return {
        'status': 'success',
        'new_items_count': added,
        'total_items': stats.get('total_items', 0),
        'scored_count': scoring.get('scored', 0),
        'scoring_status': scoring.get('status'),
        'stats': stats
    }


def main():
    """Main entry point."""
    json_output = '--json' in sys.argv
    dry_run = '--dry-run' in sys.argv

    if not json_output:
        print("=" * 50)
        print("NEWS FEED FETCHER")
        print("=" * 50)

    try:
        result = fetch_and_store(dry_run=dry_run)

        if json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"\nStatus: {result['status']}")
            print(f"New items: {result['new_items_count']}")
            if not dry_run:
                print(f"Total items: {result.get('total_items', 0)}")
                stats = result.get('stats', {})
                scored_line = f"Scored this run: {result.get('scored_count', 0)}"
                if result.get('scoring_status') != 'success':
                    scored_line += f" (scoring {result.get('scoring_status')})"
                print(scored_line)
                print(f"Unscored: {stats.get('unscored', 0)}")
                print(f"High tier: {stats.get('high_tier', 0)}")
                print(f"Medium tier: {stats.get('medium_tier', 0)}")
                print(f"Low tier: {stats.get('low_tier', 0)}")

            if dry_run and result.get('items'):
                print("\nNew items (dry run):")
                for item in result['items'][:10]:
                    print(f"  - [{item['category']}] {item['title'][:60]}...")

    except Exception as e:
        logger.error(f"Failed to fetch feeds: {e}")
        if json_output:
            print(json.dumps({'status': 'error', 'error': str(e)}))
        else:
            print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
