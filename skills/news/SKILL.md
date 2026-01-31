---
name: news
description: Display prioritized news headlines by category (crypto, macro, tech, geo)
user-invocable: true
---

# News

## Fresh Headlines

!`cd ~/Data/.datacore/modules/news && python3 lib/feed_fetcher.py 2>/dev/null && python3 -c "
import json, os
cache = os.path.expanduser('~/Data/.datacore/modules/news/data/headlines.json')
if os.path.exists(cache):
    with open(cache) as f: data = json.load(f)
    print(f'Cached headlines: {len(data.get(\"items\", []))} items')
    print(f'Last fetched: {data.get(\"fetched_at\", \"unknown\")}')
else:
    print('No cached headlines')
" 2>/dev/null || echo "Feed fetch failed - check configuration"`

## Instructions

Follow the full workflow in `~/Data/.datacore/modules/news/commands/news.md`.

Usage: `/news [category]` where category is: crypto, macro, tech, geo, or all (default)

Parse `$ARGUMENTS` for optional category filter.

Display headlines in three tiers (high/medium/low priority) based on relevance scoring. Include source, category tag, and relevance score for each item.
