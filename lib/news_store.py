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


# Module paths
MODULE_DIR = Path(__file__).parent.parent
DATA_DIR = MODULE_DIR / "data"
HEADLINES_FILE = DATA_DIR / "headlines.json"


class NewsStore:
    """JSON-based storage for news headlines."""

    def __init__(self, headlines_file: Path = HEADLINES_FILE):
        self.headlines_file = headlines_file
        self._data = None

    def _load(self) -> dict:
        """Load headlines from file."""
        if self._data is not None:
            return self._data

        if not self.headlines_file.exists():
            self._data = {
                'items': [],
                'last_updated': None,
                'stats': {}
            }
            return self._data

        try:
            with open(self.headlines_file, 'r') as f:
                self._data = json.load(f)
                return self._data
        except Exception as e:
            print(f"Warning: Failed to load headlines: {e}")
            self._data = {'items': [], 'last_updated': None, 'stats': {}}
            return self._data

    def _save(self):
        """Save headlines to file."""
        if self._data is None:
            return

        self.headlines_file.parent.mkdir(parents=True, exist_ok=True)

        self._data['last_updated'] = datetime.now(timezone.utc).isoformat()
        self._update_stats()

        with open(self.headlines_file, 'w') as f:
            json.dump(self._data, f, indent=2, default=str)

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
        data = self._load()
        items = data.get('items', [])

        for item in items:
            if item.get('id') == item_id:
                item['relevance_score'] = score
                item['tier'] = tier
                item['scored_at'] = datetime.now(timezone.utc).isoformat()
                if summary:
                    item['summary_ai'] = summary
                self._save()
                return True

        return False

    def mark_processed(self, item_id: str, output_path: Optional[str] = None) -> bool:
        """Mark an item as processed (e.g., literature note created).

        Args:
            item_id: Item ID
            output_path: Optional path to the generated output

        Returns:
            True if item was found and updated, False otherwise.
        """
        data = self._load()
        items = data.get('items', [])

        for item in items:
            if item.get('id') == item_id:
                item['processed'] = True
                item['processed_at'] = datetime.now(timezone.utc).isoformat()
                if output_path:
                    item['output_path'] = output_path
                self._save()
                return True

        return False

    def get_stats(self) -> dict:
        """Get current statistics."""
        self._load()
        self._update_stats()
        return self._data.get('stats', {})

    def get_briefing_items(self, limit: int = 20) -> dict:
        """Get items formatted for briefing display.

        Returns items grouped by tier with most relevant first.
        """
        data = self._load()
        items = data.get('items', [])

        # Get scored items from last 48 hours
        scored = [i for i in items if i.get('relevance_score') is not None]

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
        data = self._load()
        items = data.get('items', [])
        original_count = len(items)

        # Keep only recent items
        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 86400)

        recent_items = []
        for item in items:
            published = item.get('published')
            if published:
                try:
                    item_time = datetime.fromisoformat(published.replace('Z', '+00:00'))
                    if item_time.timestamp() > cutoff:
                        recent_items.append(item)
                except (ValueError, AttributeError):
                    recent_items.append(item)  # Keep items with invalid dates
            else:
                recent_items.append(item)

        # Limit total items
        data['items'] = recent_items[:max_items]
        self._save()

        return original_count - len(data['items'])


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
