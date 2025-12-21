# News Module

> News that matters, when you need it.

On-demand news aggregation with relevance scoring.

## Usage

```bash
/news              # All categories
/news crypto       # Crypto only
/news macro        # Macro/Fed/rates
/news tech         # AI and tech
/news geo          # Geopolitics
```

## Setup

```bash
# Copy template
cp data/feeds.example.yaml data/feeds.local.yaml

# Edit with your sources
```

## How It Works

1. Check if feeds are fresh (<1 hour)
2. Fetch RSS feeds + newsletter URLs
3. Score relevance using CRM context
4. Display by priority tier

## Relevance Scoring

- CRM contacts/companies → +15 boost
- Boost keywords (solana, FOMC) → +10
- Newsletter source → +5
- Demote keywords (sponsored) → -10

## Configuration

`data/feeds.local.yaml`:
```yaml
feeds:
  - name: "CoinDesk"
    url: "https://www.coindesk.com/arc/outboundfeeds/rss/"
    category: crypto
    enabled: true

boost_keywords:
  - solana
  - bitcoin
  - FOMC

demote_keywords:
  - sponsored
  - advertisement
```

## Dependencies

- Python 3.8+
- feedparser (`pip install feedparser`)

## Optional Integrations

- **CRM module**: Boost news mentioning known contacts
- **Mail module**: Extract URLs from newsletter digests

## License

MIT
