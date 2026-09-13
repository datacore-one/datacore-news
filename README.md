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

Configure an installed core, data root and qualified interpreter explicitly:

```bash
export DATACORE_LIB=/path/to/installed/core/.datacore/lib
export DATACORE_ROOT=/path/to/data
export DATACORE_PYTHON=/path/to/qualified-runtime/bin/python
export DATACORE_NEWS_CODE=/path/to/installed/news
# Optional: DATACORE_SPACE is a canonical stable space name.
"$DATACORE_PYTHON" -I "$DATACORE_NEWS_CODE/lib/news_briefing.py" --json
```

Without `DATACORE_SPACE`, exactly one verified personal space is required.
Mutable files live in that space's `.datacore/module-data/news/data/`, including
`feeds.local.yaml`, `headlines.json`, and `.processed_items.json`. Copy
`examples/feeds.example.yaml` to the selected private data directory only if
no local configuration exists. Do not overwrite a configured feed list.

An existing legacy `data`, `state`, or `settings.local.yaml` beside module code
blocks use until writers are stopped and core's `module_data_migrate.py` preserves
and verifies it. Follow core's `.datacore/lib/RUNTIME.md`; retain backups and
verify reads under the service identity before resuming. Example templates now
belong in `examples/`, outside mutable state. Loading a client never migrates,
resets or hides an existing legacy store.

Writers serialize fresh mutations and publish complete durable files. Retries
deduplicate identities and URLs without erasing scores or annotations. Stale
snapshot writers and malformed state fail explicitly. Fetching does not trim
existing items. Explicit retention writes a durable private archive before
removing items from the active store; archives require operator-managed backup
and retention. A full store refuses new writes instead of silently discarding
old data.

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

`[selected-space]/.datacore/module-data/news/data/feeds.local.yaml`:
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

- Python 3.10+ and a compatible installed Datacore core with `module_context.py`.
- The core hash-locked runtime profile, including feedparser and PyYAML. Use its
  qualified interpreter directly; News does not splice another venv into it.

RSS downloads use core's bounded transport, refuse local/private targets and
verify TLS. Provider failures remain errors. Tests use synthetic RSS through the
real parser and disposable stores; they do not contact live feeds.

To run the regression suite, create a test venv, install `requirements-test.txt`
with `--require-hashes --only-binary=:all:`, set `DATACORE_LIB` and run
`python -m pytest -q tests`. CI pins the matching core commit and checks Python
3.10, 3.12 and 3.14. Production data and external requests are unnecessary.

## Optional Integrations

- **CRM module**: Boost news mentioning known contacts
- **Mail module**: Extract URLs from newsletter digests

## License

MIT
