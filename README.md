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
cp examples/feeds.example.yaml "$(python3 lib/news_paths.py --create)/feeds.local.yaml"

# Edit with your sources
```

Mutable files live in the selected space's private
`.datacore/module-data/news/data/` (`DATACORE_SPACE`, default `personal`):
`feeds.local.yaml`, `headlines.json` and `.processed_items.json`. Do not
overwrite a configured feed list. A legacy `data/` beside the module code blocks
use until writers are stopped and core's `module_data_migrate.py` has moved it.

## State preservation

Writers take a lock, re-read the store and publish a complete file atomically,
so concurrent fetchers, scorers and newsletter imports keep each other's work.
Retries deduplicate identities and URLs without erasing scores or annotations.
Stale snapshot writers and malformed state fail explicitly instead of being
reset to empty. The store keeps the newest 500 items; anything past that, and
anything removed by explicit retention, is first written to a private
`archive/` beside `headlines.json` (back it up and prune it yourself). A store
over 16 MB refuses new writes instead of silently discarding old data.

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

`0-personal/.datacore/module-data/news/data/feeds.local.yaml`:
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

- Python 3.10+ and a Datacore core (`.datacore/lib`, or `DATACORE_LIB`) with
  `module_context.py`, `file_utils.py`, `public_download.py` and `yaml_safety.py`.
- feedparser and PyYAML (`requirements.txt`; the fetcher activates core's
  `.datacore/venv` when run as a bare `python3`).

RSS downloads use core's bounded transport and refuse local/private targets.
Tests use synthetic RSS through the real parser and disposable stores; they do
not contact live feeds. Run them with `DATACORE_LIB` pointing at a core checkout:
`python -m pytest -q` (covers `lib/tests` and `tests`; CI runs `tests`). CI pins the matching core
commit; `requirements-test.txt` is its hash-locked test environment.

## Optional Integrations

- **CRM module**: Boost news mentioning known contacts
- **Mail module**: Extract URLs from newsletter digests

## License

MIT
