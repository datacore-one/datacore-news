"""The briefing's tiers hold only items from the window it says it covers.

generate_briefing_data(hours=24) reported `hours_covered: 24` but filled its
high/medium/low tiers from every scored item in the store -- up to four days of
headlines -- so a morning briefing could lead with Saturday's news on Wednesday.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import news_briefing  # noqa: E402
from news_store import NewsStore  # noqa: E402


def _item(i, hours_ago, score, tier):
    published = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {'id': f'x{i}', 'title': f't{i}', 'category': 'crypto', 'published': published,
            'relevance_score': score, 'tier': tier}


def test_tiers_hold_only_items_inside_the_window(tmp_path, monkeypatch):
    path = tmp_path / "headlines.json"
    path.write_text(json.dumps({'items': [
        _item(1, 2, 90, 'high'),
        _item(2, 70, 95, 'high'),     # three days old, higher score
        _item(3, 5, 50, 'medium'),
        _item(4, 50, 55, 'medium'),
        _item(5, 1, None, None),      # unscored
    ], 'last_updated': None, 'stats': {}}))
    monkeypatch.setattr(news_briefing, 'NewsStore', lambda: NewsStore(path))

    b = news_briefing.generate_briefing_data(hours=24)

    assert [i['id'] for i in b['high_tier']] == ['x1']
    assert [i['id'] for i in b['medium_tier']] == ['x3']
    assert b['low_tier'] == []
