#!/usr/bin/env python3
"""
Newsletter Integration for News Module
Reads :research: tagged items from inbox.org and integrates with news pipeline.

This allows newsletter URLs (processed by mail module) to flow into the
news scoring and processing pipeline.

Usage:
    python newsletter_integration.py              # List newsletter URLs
    python newsletter_integration.py --add-queue  # Add to news queue
"""

import os
import sys
import re
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

# Module paths
MODULE_DIR = Path(__file__).parent.parent
DATA_DIR = MODULE_DIR / "data"
DATACORE_ROOT = MODULE_DIR.parent.parent.parent


def find_inbox_file() -> Optional[Path]:
    """Find inbox.org in personal space."""
    # Try common locations
    candidates = [
        DATACORE_ROOT / "0-personal" / "org" / "inbox.org",
        Path.home() / "Data" / "0-personal" / "org" / "inbox.org",
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def parse_org_item(lines: List[str]) -> Dict:
    """Parse an org-mode item into structured data."""
    if not lines:
        return {}

    headline = lines[0]

    # Extract TODO state
    todo_match = re.match(r'\*+\s+(TODO|NEXT|WAITING|DONE)\s+', headline)
    state = todo_match.group(1) if todo_match else None

    # Extract priority
    priority_match = re.search(r'\[#([ABC])\]', headline)
    priority = priority_match.group(1) if priority_match else None

    # Extract tags
    tags_match = re.search(r':([^:\s]+(?::[^:\s]+)*):$', headline)
    tags = tags_match.group(1).split(':') if tags_match else []

    # Extract title (between state/priority and tags)
    title = headline
    if todo_match:
        title = title[todo_match.end():]
    if priority_match:
        title = title.replace(f'[#{priority}]', '')
    if tags_match:
        title = title[:title.rfind(':')]
    title = title.strip()

    # Extract URLs from headline AND content
    urls = []
    url_pattern = r'\[\[([^\]]+)\]\[([^\]]+)\]\]'  # Org-mode links
    http_pattern = r'https?://[^\s\]>)]+(?<![.,;:!?])'  # Plain URLs, but not ending with punctuation

    # Include headline in search (URLs often in headline)
    full_text = '\n'.join(lines)

    # Find org-mode links
    for match in re.finditer(url_pattern, full_text):
        urls.append({
            'url': match.group(1),
            'title': match.group(2),
            'type': 'org-link'
        })

    # Find plain URLs (not already in org links)
    org_urls = {m.group(1) for m in re.finditer(url_pattern, full_text)}
    for match in re.finditer(http_pattern, full_text):
        url = match.group(0).rstrip('.,;:!?')
        if url not in org_urls:
            urls.append({
                'url': url,
                'title': None,
                'type': 'plain'
            })

    # Extract content (for properties parsing)
    content = '\n'.join(lines[1:])

    # Extract properties
    properties = {}
    in_props = False
    for line in lines[1:]:
        if ':PROPERTIES:' in line:
            in_props = True
        elif ':END:' in line:
            in_props = False
        elif in_props and ':' in line:
            prop_match = re.match(r':([^:]+):\s*(.+)', line.strip())
            if prop_match:
                properties[prop_match.group(1)] = prop_match.group(2)

    return {
        'headline': headline,
        'title': title,
        'state': state,
        'priority': priority,
        'tags': tags,
        'urls': urls,
        'properties': properties,
        'content': content
    }


def read_inbox_items(inbox_path: Path, tag_filter: str = 'research') -> List[Dict]:
    """Read items from inbox.org matching tag filter.

    Args:
        inbox_path: Path to inbox.org
        tag_filter: Tag to filter by (e.g., 'research')

    Returns:
        List of parsed items with the matching tag
    """
    if not inbox_path.exists():
        return []

    with open(inbox_path, 'r') as f:
        content = f.read()

    items = []
    current_item_lines = []
    current_level = 0

    for line in content.split('\n'):
        # Check if this is a headline
        headline_match = re.match(r'^(\*+)\s+', line)

        if headline_match:
            # Save previous item if exists
            if current_item_lines:
                item = parse_org_item(current_item_lines)
                if tag_filter in item.get('tags', []):
                    items.append(item)

            current_level = len(headline_match.group(1))
            current_item_lines = [line]
        else:
            # Add to current item if we're in one
            if current_item_lines:
                current_item_lines.append(line)

    # Don't forget last item
    if current_item_lines:
        item = parse_org_item(current_item_lines)
        if tag_filter in item.get('tags', []):
            items.append(item)

    return items


def extract_newsletter_urls(items: List[Dict]) -> List[Dict]:
    """Extract URLs from newsletter items for news pipeline.

    Args:
        items: Parsed inbox items with :research: tag

    Returns:
        List of URL entries ready for news pipeline
    """
    url_entries = []

    for item in items:
        for url_info in item.get('urls', []):
            url = url_info.get('url', '')
            if not url or not url.startswith('http'):
                continue

            # Determine category from source
            category = 'general'
            title = url_info.get('title') or item.get('title', 'Newsletter item')
            source = 'Newsletter'

            # Try to identify source from URL
            if 'bensbites' in url.lower():
                source = "Ben's Bites"
                category = 'ai-tech'
            elif 'stratechery' in url.lower():
                source = 'Stratechery'
                category = 'ai-tech'
            elif 'a16z' in url.lower() or 'andreessen' in url.lower():
                source = 'a16z'
                category = 'crypto'
            elif 'milkroad' in url.lower():
                source = 'Milk Road'
                category = 'crypto'
            elif 'therundown' in url.lower():
                source = 'The Rundown'
                category = 'ai-tech'
            elif 'substack' in url.lower():
                source = 'Substack'

            url_entries.append({
                'url': url,
                'title': title,
                'source': source,
                'category': category,
                'from_newsletter': True,
                'inbox_item': item.get('title', ''),
                'extracted_at': datetime.now(timezone.utc).isoformat()
            })

    return url_entries


def add_to_news_queue(url_entries: List[Dict], deduplicate: bool = True) -> Dict:
    """Add newsletter URLs to news headlines queue.

    Args:
        url_entries: URLs extracted from newsletters
        deduplicate: Skip URLs already in headlines.json

    Returns:
        Result with counts
    """
    import hashlib
    from news_store import NewsStore

    store = NewsStore()
    existing_items = store.get_all_items()
    existing_urls = {item.get('link', '') for item in existing_items}

    added = 0
    skipped = 0

    for entry in url_entries:
        url = entry.get('url', '')

        # Deduplicate
        if deduplicate and url in existing_urls:
            skipped += 1
            continue

        # Create news item format
        item_id = hashlib.md5(url.encode()).hexdigest()[:16]

        news_item = {
            'id': item_id,
            'title': entry.get('title', 'Newsletter item'),
            'link': url,
            'published': entry.get('extracted_at'),
            'summary': f"From newsletter: {entry.get('inbox_item', '')}",
            'source': entry.get('source', 'Newsletter'),
            'category': entry.get('category', 'general'),
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'from_newsletter': True,
            'keyword_modifier': 5,  # Slight boost for curated content
            'category_weight': 0.8,
            'relevance_score': None,
            'tier': None
        }

        # Add to store
        headlines = store._load()
        headlines['items'].insert(0, news_item)
        store._save()

        existing_urls.add(url)
        added += 1

    return {
        'added': added,
        'skipped': skipped,
        'total_checked': len(url_entries)
    }


def main():
    """Main entry point."""
    add_queue = '--add-queue' in sys.argv
    json_output = '--json' in sys.argv

    # Find inbox.org
    inbox_path = find_inbox_file()
    if not inbox_path:
        if json_output:
            print(json.dumps({'error': 'inbox.org not found'}))
        else:
            print("Error: inbox.org not found")
            print("Expected at: ~/Data/0-personal/org/inbox.org")
        sys.exit(1)

    # Read research-tagged items
    items = read_inbox_items(inbox_path, tag_filter='research')

    # Extract URLs
    url_entries = extract_newsletter_urls(items)

    if json_output:
        result = {
            'inbox_path': str(inbox_path),
            'research_items_found': len(items),
            'urls_extracted': len(url_entries),
            'urls': url_entries
        }

        if add_queue:
            queue_result = add_to_news_queue(url_entries)
            result['queue_result'] = queue_result

        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"Inbox: {inbox_path}")
        print(f"Research items found: {len(items)}")
        print(f"URLs extracted: {len(url_entries)}")

        if url_entries:
            print("\nURLs:")
            for entry in url_entries[:10]:
                print(f"  [{entry['source']}] {entry['title'][:50]}...")
                print(f"    {entry['url'][:70]}...")

        if add_queue:
            result = add_to_news_queue(url_entries)
            print(f"\nQueue update:")
            print(f"  Added: {result['added']}")
            print(f"  Skipped (duplicate): {result['skipped']}")


if __name__ == "__main__":
    main()
