---
summary: "On-demand news aggregation with AI-scored relevance and category filtering"
triggers: ["what's in the news", "news crypto", "news macro", "morning news", "market news"]
context: on_match
---

# News Module

## Purpose

Fetches RSS feeds on demand, scores each item by relevance to your work (CRM contacts, tags, boost/demote keywords), and displays tiered results by category. Caches headlines for 1 hour to avoid redundant fetches. News that matters, when you need it.

## Quick Start
> Say "what's in the news" for all categories, or "news crypto" for crypto only.

## How It Works

### Scoring
Base score per category, then modifiers: +15 CRM contact mention, +10 boost keyword match, +5 curated newsletter, -10 demote keyword. Results displayed as High / Notable / Low tiers.

### Categories
`crypto` (Bitcoin, Ethereum, Solana, DeFi), `macro` (Fed, rates, inflation), `tech` (AI, software), `geo` (politics, sanctions, trade).

## Agents & Commands

| Name | Type | When to use |
|------|------|-------------|
| `news` | skill | `/news [category]` -- fetch and display scored news |

## Key Paths

| Path | Purpose |
|------|---------|
| `data/feeds.local.yaml` | Feed sources + boost/demote keywords (gitignored) |
| `data/headlines.json` | Cached headlines (gitignored) |
| `lib/feed_fetcher.py` | RSS fetching |
| `lib/news_store.py` | Data persistence |

## Setup

```
cp data/feeds.example.yaml data/feeds.local.yaml
# Edit with your RSS sources and keywords
```

Optional: CRM module for contact-aware relevance boosting.

## Boundaries

- Feed config and headlines are PRIVATE (gitignored) -- they reveal reading habits
- Does NOT auto-fetch or push notifications -- on-demand only
- Hooks into `/today` for optional morning news summary

---

*This file covers structure, capability, and stable configuration. Learned behavior, user corrections, and operational preferences live as engrams -- call `plur_recall_hybrid` for those.*
