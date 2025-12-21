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

# Try to import feedparser, provide helpful error if missing
try:
    import feedparser
except ImportError:
    print("Error: feedparser not installed. Run: pip install feedparser")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Module paths
MODULE_DIR = Path(__file__).parent.parent
DATA_DIR = MODULE_DIR / "data"
FEEDS_FILE = DATA_DIR / "feeds.local.yaml"
FEEDS_EXAMPLE = DATA_DIR / "feeds.example.yaml"
HEADLINES_FILE = DATA_DIR / "headlines.json"
PROCESSED_FILE = DATA_DIR / ".processed_items.json"


def load_feeds_config() -> dict:
    """Load feeds configuration from YAML file."""
    config_file = FEEDS_FILE if FEEDS_FILE.exists() else FEEDS_EXAMPLE

    if not config_file.exists():
        logger.error(f"No feeds config found. Create {FEEDS_FILE}")
        return {"feeds": []}

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f) or {}

    logger.info(f"Loaded {len(config.get('feeds', []))} feeds from {config_file.name}")
    return config


def load_processed_items() -> set:
    """Load set of already processed item IDs."""
    if not PROCESSED_FILE.exists():
        return set()

    try:
        with open(PROCESSED_FILE, 'r') as f:
            data = json.load(f)
            return set(data.get('processed_ids', []))
    except Exception as e:
        logger.warning(f"Failed to load processed items: {e}")
        return set()


def save_processed_items(processed_ids: set):
    """Save set of processed item IDs."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(PROCESSED_FILE, 'w') as f:
        json.dump({
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'processed_ids': list(processed_ids)
        }, f, indent=2)


def generate_item_id(item: dict, feed_name: str) -> str:
    """Generate unique ID for a feed item."""
    # Use link as primary ID, fallback to title+date hash
    link = item.get('link', '')
    if link:
        return hashlib.md5(link.encode()).hexdigest()[:16]

    title = item.get('title', '')
    date = item.get('published', item.get('updated', ''))
    content = f"{feed_name}:{title}:{date}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


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
        feed = feedparser.parse(url)

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

    except Exception as e:
        logger.error(f"Failed to fetch {name}: {e}")
        return []


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
    """Load existing headlines from JSON file."""
    if not HEADLINES_FILE.exists():
        return {
            'items': [],
            'last_updated': None,
            'stats': {}
        }

    try:
        with open(HEADLINES_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load headlines: {e}")
        return {'items': [], 'last_updated': None, 'stats': {}}


def save_headlines(headlines: dict):
    """Save headlines to JSON file."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with open(HEADLINES_FILE, 'w') as f:
        json.dump(headlines, f, indent=2, default=str)


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

    # Load existing headlines and merge
    headlines = load_headlines()
    existing_ids = {item['id'] for item in headlines.get('items', [])}

    # Add only truly new items
    truly_new = [item for item in new_items if item['id'] not in existing_ids]

    if truly_new:
        headlines['items'] = truly_new + headlines.get('items', [])

        # Keep only last 500 items
        headlines['items'] = headlines['items'][:500]

    # Update stats
    headlines['last_updated'] = datetime.now(timezone.utc).isoformat()
    headlines['stats'] = {
        'total_items': len(headlines['items']),
        'unscored': len([i for i in headlines['items'] if i.get('relevance_score') is None]),
        'high_tier': len([i for i in headlines['items'] if i.get('tier') == 'high']),
        'medium_tier': len([i for i in headlines['items'] if i.get('tier') == 'medium']),
        'low_tier': len([i for i in headlines['items'] if i.get('tier') == 'low']),
        'by_category': {},
        'by_source': {},
    }

    # Count by category and source
    for item in headlines['items']:
        cat = item.get('category', 'unknown')
        src = item.get('source', 'unknown')
        headlines['stats']['by_category'][cat] = headlines['stats']['by_category'].get(cat, 0) + 1
        headlines['stats']['by_source'][src] = headlines['stats']['by_source'].get(src, 0) + 1

    # Save
    save_headlines(headlines)

    # Update processed IDs
    new_processed = processed_ids | {item['id'] for item in new_items}
    # Keep only last 2000 processed IDs to prevent unbounded growth
    if len(new_processed) > 2000:
        new_processed = set(list(new_processed)[-2000:])
    save_processed_items(new_processed)

    return {
        'status': 'success',
        'new_items_count': len(truly_new),
        'total_items': len(headlines['items']),
        'stats': headlines['stats']
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
