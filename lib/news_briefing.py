#!/usr/bin/env python3
"""
News Briefing Generator
Generates formatted news briefing from scored headlines.

Usage:
    python news_briefing.py          # Full briefing output
    python news_briefing.py --json   # JSON output for programmatic use
    python news_briefing.py --short  # Short summary only
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Import from sibling module
sys.path.insert(0, str(Path(__file__).parent))
from news_store import NewsStore


def generate_briefing_data(hours: int = 24) -> dict:
    """Generate briefing data structure.

    Args:
        hours: Include items from last N hours

    Returns:
        Structured briefing data
    """
    store = NewsStore()
    stats = store.get_stats()
    briefing_items = store.get_briefing_items(limit=15)

    # Calculate time-based stats
    recent_items = store.get_recent_items(hours=hours)

    briefing = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'date': datetime.now().strftime('%Y-%m-%d'),
        'day': datetime.now().strftime('%A'),
        'hours_covered': hours,

        'summary': {
            'total_headlines': stats.get('total_items', 0),
            'unscored': stats.get('unscored', 0),
            'recent_count': len(recent_items),
            'high_tier_count': len(briefing_items.get('high', [])),
            'medium_tier_count': len(briefing_items.get('medium', [])),
            'low_tier_count': len(briefing_items.get('low', [])),
        },

        'by_category': stats.get('by_category', {}),
        'by_source': stats.get('by_source', {}),

        'high_tier': briefing_items.get('high', []),
        'medium_tier': briefing_items.get('medium', []),
        'low_tier': briefing_items.get('low', []),
    }

    return briefing


def format_item(item: dict, include_summary: bool = True) -> str:
    """Format a single news item for display."""
    title = item.get('title', 'No title')
    link = item.get('link', '')
    source = item.get('source', 'Unknown')
    category = item.get('category', '')
    score = item.get('relevance_score', 0)
    summary = item.get('summary_ai') or item.get('summary', '')

    # Truncate long titles
    if len(title) > 80:
        title = title[:77] + "..."

    lines = []
    lines.append(f"  [{score:3d}] {title}")
    lines.append(f"        Source: {source} | Category: {category}")

    if link:
        lines.append(f"        Link: {link}")

    if include_summary and summary:
        # Truncate summary
        if len(summary) > 200:
            summary = summary[:197] + "..."
        lines.append(f"        {summary}")

    return "\n".join(lines)


def format_briefing(briefing: dict, short: bool = False) -> str:
    """Format briefing as human-readable text."""
    output = []
    output.append("=" * 60)
    output.append(f"NEWS BRIEFING - {briefing['day']}, {briefing['date']}")
    output.append("=" * 60)

    summary = briefing.get('summary', {})

    output.append("\n## OVERVIEW\n")
    output.append(f"  Headlines tracked: {summary.get('total_headlines', 0)}")
    output.append(f"  Recent (24h): {summary.get('recent_count', 0)}")
    output.append(f"  Awaiting scoring: {summary.get('unscored', 0)}")

    # Category breakdown
    by_category = briefing.get('by_category', {})
    if by_category:
        output.append("\n  By Category:")
        for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
            output.append(f"    {cat}: {count}")

    # High tier items
    high_tier = briefing.get('high_tier', [])
    output.append(f"\n## HIGH PRIORITY ({len(high_tier)} items)\n")

    if high_tier:
        for item in high_tier[:5 if short else 10]:
            output.append(format_item(item, include_summary=not short))
            output.append("")
    else:
        output.append("  No high-priority items")

    if not short:
        # Medium tier items
        medium_tier = briefing.get('medium_tier', [])
        output.append(f"\n## MEDIUM PRIORITY ({len(medium_tier)} items)\n")

        if medium_tier:
            for item in medium_tier[:7]:
                output.append(format_item(item, include_summary=False))
                output.append("")
        else:
            output.append("  No medium-priority items")

        # Low tier summary
        low_tier = briefing.get('low_tier', [])
        output.append(f"\n## LOW PRIORITY ({len(low_tier)} items)\n")

        if low_tier:
            output.append("  Headlines only (low relevance):")
            for item in low_tier[:10]:
                title = item.get('title', 'No title')
                if len(title) > 70:
                    title = title[:67] + "..."
                source = item.get('source', '')
                output.append(f"    - {title} ({source})")
        else:
            output.append("  No low-priority items")

    output.append("\n" + "=" * 60)

    return "\n".join(output)


def format_for_market_briefing(briefing: dict, max_items: int = 5) -> dict:
    """Format news data for inclusion in /market-briefing.

    Returns a compact structure suitable for embedding in market briefing.
    """
    high_tier = briefing.get('high_tier', [])

    # Select most relevant items across categories
    items = []
    seen_categories = set()

    for item in high_tier:
        category = item.get('category', 'general')
        # Prefer variety - one item per category first
        if category not in seen_categories:
            items.append({
                'title': item.get('title', '')[:80],
                'source': item.get('source', ''),
                'category': category,
                'score': item.get('relevance_score', 0),
                'summary': (item.get('summary_ai') or item.get('summary', ''))[:150],
            })
            seen_categories.add(category)

        if len(items) >= max_items:
            break

    # Fill remaining slots with highest scores
    if len(items) < max_items:
        for item in high_tier:
            if item.get('id') not in [i.get('id') for i in items]:
                items.append({
                    'title': item.get('title', '')[:80],
                    'source': item.get('source', ''),
                    'category': item.get('category', ''),
                    'score': item.get('relevance_score', 0),
                    'summary': (item.get('summary_ai') or item.get('summary', ''))[:150],
                })
                if len(items) >= max_items:
                    break

    return {
        'timestamp': briefing.get('timestamp'),
        'high_priority_count': len(high_tier),
        'items': items,
    }


def main():
    """Main entry point."""
    json_output = '--json' in sys.argv
    short = '--short' in sys.argv
    market = '--market' in sys.argv

    try:
        briefing = generate_briefing_data()

        if json_output:
            print(json.dumps(briefing, indent=2, default=str))
        elif market:
            # Output for market briefing integration
            market_data = format_for_market_briefing(briefing)
            print(json.dumps(market_data, indent=2))
        else:
            print(format_briefing(briefing, short=short))

    except Exception as e:
        if json_output:
            print(json.dumps({'error': str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
