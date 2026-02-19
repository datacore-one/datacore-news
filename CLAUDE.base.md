# News Module

On-demand news aggregation with relevance scoring.

## Command

```
/news              # All categories
/news crypto       # Crypto only
/news macro        # Macro/Fed/rates
/news tech         # AI and tech
/news geo          # Geopolitics
```

## How It Works

1. **Freshness check** - Skip fetch if <1 hour old
2. **Fetch feeds** - RSS + newsletter URLs from inbox.org
3. **Score relevance** - Using CRM contacts, tags, keywords
4. **Display by tier** - High/Notable/Low with category labels

## Relevance Scoring

Base scores by category, then modifiers:
- +15 if mentions CRM contact/company
- +10 if matches boost keyword (solana, FOMC, etc.)
- +5 if from curated newsletter
- -10 if matches demote keyword

## Categories

| Category | Matches |
|----------|---------|
| crypto | Bitcoin, Ethereum, Solana, DeFi |
| macro | Fed, rates, inflation, economy |
| tech | AI, software, technology |
| geo | Politics, sanctions, trade |

## Context Sources

- **CRM contacts** - Boost news about known entities
- **Tags** - Work areas (configured in tags.yaml)
- **feeds.local.yaml** - User boost/demote keywords
- **inbox.org** - Newsletter URLs with :research: tag

## Configuration

`data/feeds.local.yaml`:
```yaml
feeds:
  - name: "CoinDesk"
    url: "https://www.coindesk.com/arc/outboundfeeds/rss/"
    category: crypto

boost_keywords:
  - solana
  - FOMC

demote_keywords:
  - sponsored
```

## Privacy

Feed config and headlines are PRIVATE (gitignored) - they reveal reading habits.

## Files

| File | Purpose |
|------|---------|
| `data/feeds.local.yaml` | Your feed sources (gitignored) |
| `data/headlines.json` | Cached headlines (gitignored) |
| `lib/feed_fetcher.py` | RSS fetching |
| `lib/news_store.py` | Data persistence |
