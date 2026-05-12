---
name: today-hook
description: today-hook command
recall:
  # DIP-0029 default — engrams scoped to this command + tag-matched.
  scopes:
    - command:today-hook
  tags:
    - today-hook
---

# News Hook: /today Integration

## Command Context

### When to Reference News Module

**Always reference when:**
- /today command is invoked (automatic hook)
- User requests morning briefing or daily summary
- User wants news integrated into their daily workflow
- User asks about news in /today output

**Key decisions the module informs:**
- How to synthesize news into narrative paragraph (not bullet points)
- Which items to include (past 24 hours, high/medium tier only)
- How to structure the summary (macro theme → specific developments → crypto)
- When to fetch fresh headlines (if >4 hours old)
- Tone and style (analytical, Bloomberg-like)

### Quick Reference

| Question | Answer |
|----------|--------|
| What format to use? | Synthesized narrative paragraph (2-3 paragraphs) |
| What items to include? | Past 24 hours, high/medium tier, grouped by category |
| When to refresh data? | If headlines >4 hours old, fetch fresh first |
| What tone to use? | Analytical, concise, professional (like Bloomberg) |

### Agents This Command Invokes

| Agent | Purpose |
|-------|---------|
| (None directly) | Reads from headlines.json, may call feed_fetcher.py if stale |

### Integration Points

- **/today command** - Parent command that calls this hook
- **headlines.json** - Data source for news items
- **feed_fetcher.py** - Refreshes headlines if stale (>4 hours)
- **News scoring** - Uses relevance scores to select top items

---

This hook adds a news summary paragraph to the daily briefing.

## Trigger

Called by `/today` command when news module is installed.

## Section to Add

### News Summary

Generate a **synthesized narrative paragraph** that captures the day's news themes, NOT just a list of headlines. The summary should read like a morning briefing from an analyst.

```
NEWS SUMMARY
────────────
[2-3 paragraph synthesis of today's news landscape]

The first paragraph covers the overall market sentiment and major themes.
The second paragraph highlights specific developments worth noting.
The third paragraph (optional) covers crypto-specific news if relevant.
```

**Example Output:**

```markdown
### News Summary

Markets are digesting the Fed's hawkish stance from yesterday's meeting, with rate cut expectations for 2025 now reduced from four to two. This shift is rippling through risk assets, with both equities and crypto showing weakness. Geopolitically, tensions remain elevated as the Australian PM announced a major intelligence review following recent security incidents.

In crypto, analysts are signaling caution as Bitcoin demand metrics shrink—a potential bear market indicator according to CryptoQuant data. However, institutional interest remains strong with BlackRock's BTC ETF crossing $25B in yearly inflows despite the price slump. Ethereum developers are pushing forward with the 'Glamsterdam' upgrade aimed at addressing MEV fairness concerns.

On the business front, stagflation concerns are resurfacing amid mixed economic signals, while tech continues its AI infrastructure buildout with several major funding rounds announced this week.
```

## Data Sources

1. **Load headlines**: Read from `.datacore/modules/news/data/headlines.json`
2. **Filter recent**: Only items from past 24 hours
3. **Group by category**: geopolitics → Global, macro/fed → Business, crypto → Crypto
4. **Select top items**: Highest scored items per category

## Implementation

```python
import sys
sys.path.insert(0, '.datacore/modules/news/lib')
from news_store import NewsStore

store = NewsStore()
items = store.get_all_items()

# Filter to past 24 hours and group
from datetime import datetime, timedelta
cutoff = datetime.now() - timedelta(hours=24)

global_items = [i for i in items if i.get('category') in ['geopolitics'] and i.get('tier') in ['high', 'medium']]
business_items = [i for i in items if i.get('category') in ['macro', 'fed'] and i.get('tier') in ['high', 'medium']]
crypto_items = [i for i in items if i.get('category') == 'crypto' and i.get('tier') in ['high', 'medium']]

# Get top 3-5 for each
top_global = sorted(global_items, key=lambda x: x.get('relevance_score') or 50, reverse=True)[:3]
top_business = sorted(business_items, key=lambda x: x.get('relevance_score') or 70, reverse=True)[:3]
top_crypto = sorted(crypto_items, key=lambda x: x.get('relevance_score') or 70, reverse=True)[:3]
```

## Output Format

Generate a **synthesized narrative** (2-3 paragraphs) that weaves together the key themes. Do NOT use bullet points or category headers. Write as if you're a market analyst giving a morning briefing.

**Structure:**
1. **Opening paragraph**: Overall sentiment, major macro theme, market direction
2. **Middle paragraph**: Specific developments worth noting (crypto, tech, geopolitics)
3. **Closing sentence** (optional): What to watch today

```markdown
### News Summary

Markets are showing caution following the Fed's hawkish December meeting, with rate cut expectations for 2025 now reduced significantly. This is weighing on risk assets across the board.

In crypto, Bitcoin demand metrics are shrinking according to CryptoQuant—a potential bear market signal—though institutional flows remain positive with BlackRock's ETF hitting $25B in yearly inflows. The Ethereum community is focused on the upcoming 'Glamsterdam' upgrade targeting MEV fairness. Meanwhile, geopolitical tensions persist with Australia announcing a major intelligence review.

Key theme today: risk-off sentiment as markets reprice Fed expectations.
```

**Tone**: Analytical, concise, professional. Like a Bloomberg terminal summary.

## Conditions

| Condition | Behavior |
|-----------|----------|
| No headlines cached | Fetch fresh: `python3 .datacore/modules/news/lib/feed_fetcher.py` |
| Headlines >4 hours old | Fetch fresh before summarizing |
| No items in category | Skip that category line |
| All categories empty | Show "No recent news available" |

## Freshness Check

Before generating summary:
1. Check `last_updated` in headlines.json
2. If older than 4 hours, run feed fetcher first
3. Then generate summary from fresh data

## Tone

- Factual, brief summaries
- No sensationalism
- Focus on relevance to work context (trading, crypto, macro)
- Business-like tone matching Data's analytical style
