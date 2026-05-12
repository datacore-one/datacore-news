---
name: news
description: news command
recall:
  # DIP-0029 default — engrams scoped to this command + tag-matched.
  scopes:
    - command:news
  tags:
    - news
---

# /news

## Command Context

### When to Reference News Module

**Always reference when:**
- User requests news, headlines, or market updates
- User wants to check specific categories (crypto, macro, tech, geo)
- User mentions staying informed or catching up on developments
- User refers to newsletters, RSS feeds, or news sources

**Key decisions the module informs:**
- Which news items are relevant (based on CRM contacts, tags, boost keywords)
- How to score and tier items (high/medium/low priority)
- When to fetch fresh data vs use cached headlines
- Which categories to display and how to filter
- Whether to integrate newsletter URLs from inbox.org

### Quick Reference

| Question | Answer |
|----------|--------|
| What categories exist? | crypto, macro, tech, geo, all (default) |
| How fresh is the data? | Cached <1 hour, fetched if >1 hour old |
| What determines relevance? | Base score + CRM matches + boost keywords - demote keywords |
| Where do headlines cache? | `.datacore/modules/news/data/headlines.json` |

### Agents This Command Invokes

| Agent | Purpose |
|-------|---------|
| (None directly) | Uses feed_fetcher.py and newsletter_integration.py scripts |

### Integration Points

- **CRM contacts** - `.datacore/state/crm/contacts-index.yaml` for relevance boosting
- **Tags registry** - `.datacore/config/tags.yaml` for work-relevant topics
- **Boost keywords** - `data/feeds.local.yaml` for user-defined terms
- **Newsletter URLs** - Extracts from inbox.org `:research:` tasks

---

On-demand news aggregation with relevance scoring.

## Usage

```
/news              # All categories
/news crypto       # Crypto only
/news macro        # Macro/Fed/rates
/news tech         # AI and tech
/news geo          # Geopolitics
```

## Workflow

### Step 1: Check Freshness

Read last fetch timestamp from `data/headlines.json`:
- If <1 hour old: skip fetch, use cached
- If >1 hour old: fetch new items

```python
from news_store import NewsStore
store = NewsStore()
data = store._load()
last_updated = data.get('last_updated')
# Compare to now, decide if fetch needed
```

### Step 2: Fetch if Stale

If stale, run feed fetcher:

```bash
python3 .datacore/modules/news/lib/feed_fetcher.py
```

Also collect newsletter URLs from inbox.org:

```bash
python3 .datacore/modules/news/lib/newsletter_integration.py --add-queue
```

Report: "Fetched X new items from Y feeds"

### Step 3: Load Context

Load relevance boosters from:

**CRM contacts** (`.datacore/state/crm/contacts-index.yaml`):
- Company names → boost if mentioned
- People names → boost if mentioned
- Organizations → boost if mentioned

**Tags** (`.datacore/config/tags.yaml`):
- Work areas (configured in tags.yaml)
- Focus areas from user's system

**Boost keywords** (`data/feeds.local.yaml`):
- User-defined keywords like "solana", "FOMC", etc.

### Step 4: Score Unscored Items

For each unscored item, calculate relevance (0-100):

**Base score by category:**
- crypto: 70
- macro/fed: 70
- geopolitics: 50
- ai-tech: 60
- general: 40

**Modifiers:**
- +15 if title mentions CRM contact/company
- +10 if matches boost keyword
- +5 if from newsletter (curated)
- -10 if matches demote keyword

**Tier assignment:**
- 70+: high
- 40-69: medium
- <40: low

### Step 5: Display Results

Filter by category if specified, show by tier:

```
NEWS - 2025-12-21 (32 items, 15 new)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HIGH PRIORITY
[92] Fed Holds Rates at 4.5%
     Yahoo Finance | macro

[85] Arthur Hayes: Love Language
     Substack | crypto

[78] Solana TVL Hits $8B ATH
     CoinDesk | crypto

NOTABLE
[65] OpenAI Announces GPT-5
     TechMeme | tech

[58] Oil Prices Drop on OPEC News
     Yahoo Finance | macro

LOW (12 items hidden, use --all to show)
```

### Step 6: Offer Actions

```
Options:
1. Open [article number]
2. Refresh feeds now
3. Show all (including low priority)
```

## Category Mapping

| Arg | Matches |
|-----|---------|
| `crypto` | crypto, defi, bitcoin, ethereum, solana |
| `macro` | macro, fed, rates, economy, inflation |
| `tech` | ai-tech, technology, software |
| `geo` | geopolitics, politics, sanctions |
| `all` | everything (default) |

## Context Sources

| Source | Used For |
|--------|----------|
| CRM contacts | Boost news mentioning known entities |
| Tags registry | Identify work-relevant topics |
| feeds.local.yaml | User boost/demote keywords |
| inbox.org :research: | Newsletter URLs |

## Error Handling

**No feeds configured:**
```
No feeds configured. Copy the template:
  cp data/feeds.example.yaml data/feeds.local.yaml
```

**All feeds failing:**
```
Could not fetch any feeds. Check network connection.
Last successful fetch: [timestamp]
```

**No items match filter:**
```
No [category] news found. Try:
  /news        # Show all categories
  /news crypto # Different category
```

## Your Boundaries

**YOU CAN:**
- Fetch RSS feeds on demand
- Read CRM contacts for context
- Score items based on relevance
- Filter by category

**YOU CANNOT:**
- Create literature notes (that's research module)
- Schedule background tasks
- Modify CRM or tag data

**YOU MUST:**
- Check freshness before fetching
- Use CRM context for relevance
- Show clear category labels
- Offer follow-up actions
