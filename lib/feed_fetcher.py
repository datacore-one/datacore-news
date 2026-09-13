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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from news_context import context, MODULE_DIR
from news_store import NewsStore
from module_context import parse_json, read_text
from file_utils import atomic_write_json, file_lock
from public_download import download
from yaml_safety import UniqueStringKeyLoader
import feedparser
import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def _data_file(name):
    return context().data / name


def load_feeds_config() -> dict:
    selected = context(create=False)
    local = selected.data / 'feeds.local.yaml'
    raw = read_text(selected.space, local, limit=1024**2)
    if raw is None:
        example = MODULE_DIR / 'examples/feeds.example.yaml'
        raw = read_text(MODULE_DIR, example, limit=1024**2)
    if raw is None:
        raise ValueError('news feed configuration is missing')
    config = yaml.load(raw, Loader=UniqueStringKeyLoader)
    if not isinstance(config, dict) or not isinstance(config.get('feeds'), list) or len(config['feeds']) > 64:
        raise ValueError('invalid or oversized news feed configuration')
    if any(not isinstance(feed, dict) for feed in config['feeds']):
        raise ValueError('invalid news feed entry')
    return config


def load_processed_items() -> set:
    selected = context(create=False)
    raw = read_text(selected.space, selected.data / '.processed_items.json')
    if raw is None:
        return set()
    data = parse_json(raw)
    if (not isinstance(data, dict) or not isinstance(data.get('processed_ids'), list)
            or any(not isinstance(item, str) or not item for item in data['processed_ids'])):
        raise ValueError('invalid processed news identities; original preserved')
    return set(data['processed_ids'])


def save_processed_items(processed_ids: set):
    if any(not isinstance(item, str) or not item for item in processed_ids):
        raise ValueError('invalid processed news identities')
    target = _data_file('.processed_items.json')
    with file_lock(target):
        combined = load_processed_items() | processed_ids
        data = {'last_updated': datetime.now(timezone.utc).isoformat(), 'processed_ids': sorted(combined)}
        if len(json.dumps(data, indent=2).encode()) + 1 > 16 * 1024**2:
            raise ValueError('processed identity store exceeds limit; explicit archival required')
        atomic_write_json(target, data)


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
        feed = feedparser.parse(download(url, max_bytes=4 * 1024**2))

        if feed.bozo and feed.bozo_exception:
            raise ValueError('invalid RSS response')

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
        raise ValueError('news feed retrieval or parsing failed') from None


def fetch_all_feeds(config: dict, processed_ids: set) -> list:
    """Fetch all enabled feeds and return new items."""
    feeds = config.get('feeds', [])
    all_items = []

    for feed_config in feeds:
        items = parse_feed(feed_config)

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


def load_headlines() -> dict:
    return NewsStore()._load()


def save_headlines(headlines: dict):
    """Merge additions while preserving existing scores and annotations."""
    NewsStore._validate(headlines)
    return NewsStore().add_items(headlines['items'])


def apply_keyword_boost(item: dict, config: dict) -> int:
    """Apply keyword boost/demote to calculate base relevance modifier."""
    boost_keywords = config.get('boost_keywords', [])
    demote_keywords = config.get('demote_keywords', [])

    title_lower = item.get('title', '').lower()
    summary_lower = item.get('summary', '').lower()
    text = f"{title_lower} {summary_lower}"

    modifier = 0

    for keyword in boost_keywords:
        if keyword.lower() in text:
            modifier += 10

    for keyword in demote_keywords:
        if keyword.lower() in text:
            modifier -= 15

    return modifier


def fetch_and_store(dry_run: bool = False) -> dict:
    """Fetch feeds and store new items."""
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

    # Apply keyword modifiers
    category_weights = config.get('category_weights', {})
    for item in new_items:
        # Base relevance modifier from keywords
        item['keyword_modifier'] = apply_keyword_boost(item, config)

        # Category weight
        category = item.get('category', 'general')
        item['category_weight'] = category_weights.get(category, 0.5)

        # Mark as unscored
        item['relevance_score'] = None
        item['tier'] = None

    # A repeated feed entry cannot reset a scored item, and concurrent writers
    # merge under the same store lock. Retention is an explicit archived action.
    additions = {}
    for item in new_items:
        additions.setdefault(item['id'], item)
    store = NewsStore()
    added = store.add_items(list(additions.values()))
    # Publication precedes fetch-history acknowledgement. A crash here retries
    # idempotently against the retained authoritative items.
    save_processed_items({item['id'] for item in new_items})
    stats = store.get_stats()
    return {'status': 'success', 'new_items_count': added,
            'total_items': stats['total_items'], 'stats': stats}


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
