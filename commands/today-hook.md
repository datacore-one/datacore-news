# News Hook: /today Integration

This hook adds a news summary paragraph to the daily briefing.

## Trigger

Called by `/today` command when news module is installed.

## Section to Add

### News Summary

A concise paragraph summarizing key headlines across global news, business, and crypto.

```
NEWS SUMMARY
────────────
Global: [1-2 sentence summary of major world events]
Business: [1-2 sentence summary of market/macro news]
Crypto: [1-2 sentence summary of crypto developments]

Top Stories:
• [Most important headline 1]
• [Most important headline 2]
• [Most important headline 3]
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

Generate a natural paragraph summarizing each category, then list top 3 stories:

```markdown
### News Summary

**Global**: Australian PM announces intelligence review following security incident. Violence continues in South Africa with multiple casualties.

**Business**: Markets digest Fed's hawkish stance on rates. Stagflation concerns resurface amid mixed economic signals.

**Crypto**: Bitcoin demand shrinking signals potential bear market according to analysts. Ethereum's Glamsterdam upgrade aims to address MEV fairness.

**Top Stories**:
• Fed holds rates steady, signals fewer cuts in 2025
• Bitcoin demand shrinks as analysts signal bear market
• Australian PM announces major intelligence review
```

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
