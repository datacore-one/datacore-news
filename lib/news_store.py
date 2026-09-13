#!/usr/bin/env python3
"""
News Store - JSON persistence layer for News Module
Provides API for reading/writing headlines and managing tiers.

Usage:
    from news_store import NewsStore

    store = NewsStore()
    unscored = store.get_unscored_items()
    store.update_score(item_id, score=85, tier='high')
    high_tier = store.get_items_by_tier('high')
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


from news_context import context
from module_context import parse_json, read_text
from file_utils import atomic_write_text, file_lock, fsync_directory

MAX_STORE_BYTES = 16 * 1024**2


class NewsStore:
    """Fresh reads and serialized mutations; no stale whole-store replacement."""

    def __init__(self, headlines_file: Optional[Path] = None):
        self.headlines_file = Path(headlines_file) if headlines_file is not None else context().data / 'headlines.json'
        self._data = None
        self._loaded_raw = None

    @staticmethod
    def _validate(data):
        if not isinstance(data, dict) or not isinstance(data.get('items'), list):
            raise ValueError('invalid news state; original preserved')
        seen = set()
        for item in data['items']:
            if (not isinstance(item, dict) or not isinstance(item.get('id'), str)
                    or not item['id'] or item['id'] in seen):
                raise ValueError('invalid or duplicate news identity; original preserved')
            seen.add(item['id'])
        return data

    def _read(self):
        path = self.headlines_file
        raw = read_text(path.parent.resolve(strict=True), path.parent.resolve(strict=True) / path.name,
                        limit=MAX_STORE_BYTES)
        data = {'items': [], 'last_updated': None, 'stats': {}} if raw is None else parse_json(raw)
        return self._validate(data), raw

    def _load(self) -> dict:
        self._data, self._loaded_raw = self._read()
        return self._data

    def _publish(self):
        self._validate(self._data)
        self._data['last_updated'] = datetime.now(timezone.utc).isoformat()
        self._update_stats()
        content = json.dumps(self._data, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
        if len(content.encode('utf-8')) > MAX_STORE_BYTES:
            raise ValueError('news store exceeds limit; archive explicitly before retrying')
        atomic_write_text(self.headlines_file, content)
        self._loaded_raw = content

    def _save(self):
        """Compatibility for snapshot callers: stale snapshots must refuse."""
        if self._data is None:
            return
        with file_lock(self.headlines_file):
            _, current = self._read()
            if current != self._loaded_raw:
                raise ValueError('news changed since read; retry the intended mutation')
            self._publish()

    def _mutate(self, change):
        with file_lock(self.headlines_file):
            self._load()
            before = json.dumps(self._data, sort_keys=True)
            result = change(self._data)
            if json.dumps(self._data, sort_keys=True) != before:
                self._publish()
            return result

    def add_items(self, additions):
        """Idempotently add new identities without resetting scored records."""
        self._validate({'items': additions})
        def add(data):
            ids = {item['id']: item for item in data['items']}
            urls = {item.get('link') for item in data['items'] if item.get('link')}
            new = []
            for item in additions:
                if item['id'] in ids:
                    if item.get('link') != ids[item['id']].get('link'):
                        raise ValueError('news identity conflict; original preserved')
                    continue
                if item.get('link') and item['link'] in urls:
                    continue
                new.append(dict(item))
                ids[item['id']] = item
                if item.get('link'):
                    urls.add(item['link'])
            data['items'] = new + data['items']
            return len(new)
        return self._mutate(add)

    def _update_stats(self):
        """Update statistics in data."""
        items = self._data.get('items', [])

        self._data['stats'] = {
            'total_items': len(items),
            'unscored': len([i for i in items if i.get('relevance_score') is None]),
            'high_tier': len([i for i in items if i.get('tier') == 'high']),
            'medium_tier': len([i for i in items if i.get('tier') == 'medium']),
            'low_tier': len([i for i in items if i.get('tier') == 'low']),
            'processed': len([i for i in items if i.get('processed', False)]),
            'by_category': {},
            'by_source': {},
        }

        for item in items:
            cat = item.get('category', 'unknown')
            src = item.get('source', 'unknown')
            self._data['stats']['by_category'][cat] = \
                self._data['stats']['by_category'].get(cat, 0) + 1
            self._data['stats']['by_source'][src] = \
                self._data['stats']['by_source'].get(src, 0) + 1

    def get_all_items(self) -> list:
        """Get all items."""
        return self._load().get('items', [])

    def get_item_by_id(self, item_id: str) -> Optional[dict]:
        """Get a specific item by ID."""
        items = self._load().get('items', [])
        for item in items:
            if item.get('id') == item_id:
                return item
        return None

    def get_unscored_items(self, limit: int = 50) -> list:
        """Get items that haven't been scored yet."""
        items = self._load().get('items', [])
        unscored = [i for i in items if i.get('relevance_score') is None]
        return unscored[:limit]

    def get_items_by_tier(self, tier: str, processed: Optional[bool] = None) -> list:
        """Get items by tier (high, medium, low).

        Args:
            tier: 'high', 'medium', or 'low'
            processed: If True, only processed items. If False, only unprocessed.
                      If None, all items in tier.
        """
        items = self._load().get('items', [])
        tier_items = [i for i in items if i.get('tier') == tier]

        if processed is not None:
            tier_items = [i for i in tier_items if i.get('processed', False) == processed]

        return tier_items

    def get_items_by_category(self, category: str) -> list:
        """Get items by category."""
        items = self._load().get('items', [])
        return [i for i in items if i.get('category') == category]

    def get_items_by_source(self, source: str) -> list:
        """Get items by source."""
        items = self._load().get('items', [])
        return [i for i in items if i.get('source') == source]

    def get_recent_items(self, hours: int = 24, scored_only: bool = True) -> list:
        """Get items from the last N hours."""
        items = self._load().get('items', [])
        cutoff = datetime.now(timezone.utc).timestamp() - (hours * 3600)

        recent = []
        for item in items:
            published = item.get('published')
            if published:
                try:
                    item_time = datetime.fromisoformat(published.replace('Z', '+00:00'))
                    if item_time.tzinfo is None:
                        item_time = item_time.replace(tzinfo=timezone.utc)
                    if item_time.timestamp() > cutoff:
                        if not scored_only or item.get('relevance_score') is not None:
                            recent.append(item)
                except (ValueError, AttributeError):
                    pass

        return recent

    def update_score(self, item_id: str, score: int, tier: str,
                     summary: Optional[str] = None) -> bool:
        """Update the relevance score and tier for an item.

        Args:
            item_id: Item ID
            score: Relevance score (0-100)
            tier: 'high', 'medium', or 'low'
            summary: Optional AI-generated summary

        Returns:
            True if item was found and updated, False otherwise.
        """
        if type(score) is not int or not 0 <= score <= 100 or tier not in ('high', 'medium', 'low'):
            raise ValueError('invalid news score or tier')
        if summary is not None and not isinstance(summary, str):
            raise ValueError('invalid news summary')
        def update(data):
            for item in data['items']:
                if item['id'] == item_id:
                    item.update(relevance_score=score, tier=tier, scored_at=datetime.now(timezone.utc).isoformat())
                    if summary is not None:
                        item['summary_ai'] = summary
                    return True
            return False
        return self._mutate(update)

    def mark_processed(self, item_id: str, output_path: Optional[str] = None) -> bool:
        """Mark an item as processed (e.g., literature note created).

        Args:
            item_id: Item ID
            output_path: Optional path to the generated output

        Returns:
            True if item was found and updated, False otherwise.
        """
        if output_path is not None and not isinstance(output_path, str):
            raise ValueError('invalid output path')
        def update(data):
            for item in data['items']:
                if item['id'] == item_id:
                    item.update(processed=True, processed_at=datetime.now(timezone.utc).isoformat())
                    if output_path is not None:
                        item['output_path'] = output_path
                    return True
            return False
        return self._mutate(update)

    def get_stats(self) -> dict:
        """Get current statistics."""
        self._load()
        self._update_stats()
        return self._data.get('stats', {})

    def get_briefing_items(self, limit: int = 20, hours: int = 48) -> dict:
        """Get items formatted for briefing display.

        Returns items grouped by tier with most relevant first.
        """
        scored = self.get_recent_items(hours=hours, scored_only=True)

        # Sort by score (highest first)
        scored.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)

        return {
            'high': [i for i in scored if i.get('tier') == 'high'][:limit],
            'medium': [i for i in scored if i.get('tier') == 'medium'][:limit],
            'low': [i for i in scored if i.get('tier') == 'low'][:limit],
            'stats': self.get_stats()
        }

    def cleanup_old_items(self, max_age_days: int = 7, max_items: int = 500) -> int:
        """Remove old items to prevent unbounded growth.

        Args:
            max_age_days: Remove items older than this
            max_items: Maximum items to keep

        Returns:
            Number of items removed.
        """
        if type(max_age_days) is not int or max_age_days < 0 or type(max_items) is not int or max_items < 0:
            raise ValueError('invalid retention limits')
        def cleanup(data):
            cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
            recent, retired = [], []
            for item in data['items']:
                try:
                    published = datetime.fromisoformat(item['published'].replace('Z', '+00:00'))
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    expired = published.timestamp() <= cutoff
                except (ValueError, TypeError, KeyError, AttributeError):
                    expired = False
                (retired if expired or len(recent) >= max_items else recent).append(item)
            if retired:
                import hashlib
                content = json.dumps({'items': retired}, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
                digest = hashlib.sha256(content.encode()).hexdigest()
                archive = self.headlines_file.parent / 'archive'
                archive.mkdir(mode=0o700, exist_ok=True)
                if archive.is_symlink() or archive.stat().st_mode & 0o077:
                    raise ValueError('news archive must be private and unaliased')
                # Make the archive directory reachable after a crash before
                # publishing a store that omits the retired items.
                fsync_directory(self.headlines_file.parent)
                target = archive / (digest + '.json')
                existing = read_text(archive, target, limit=MAX_STORE_BYTES)
                if existing is not None and existing != content:
                    raise ValueError('news archive conflict')
                atomic_write_text(target, content)
                data['items'] = recent
            return len(retired)
        return self._mutate(cleanup)


# Convenience functions
def get_store() -> NewsStore:
    """Get a NewsStore instance."""
    return NewsStore()


if __name__ == "__main__":
    # Quick test
    store = NewsStore()
    stats = store.get_stats()
    print(f"Total items: {stats.get('total_items', 0)}")
    print(f"Unscored: {stats.get('unscored', 0)}")
    print(f"High tier: {stats.get('high_tier', 0)}")
    print(f"Medium tier: {stats.get('medium_tier', 0)}")
    print(f"Low tier: {stats.get('low_tier', 0)}")
