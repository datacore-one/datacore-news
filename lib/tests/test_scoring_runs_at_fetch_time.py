"""Scoring happens during the fetch, over the whole backlog, and never costs it.

The store keeps only the newest 500 items -- about four days at 120-260 items a
day -- so an item not scored at fetch time ages out unscored. That is how the
store came to hold 500 items with 0 scored and /today reported "NEWS:
UNAVAILABLE (unscored backlog)" for five sessions running.
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import feed_fetcher as F  # noqa: E402
import news_scorer as S  # noqa: E402
from news_store import NewsStore  # noqa: E402


def _store(tmp_path, items):
    path = tmp_path / "headlines.json"
    path.write_text(json.dumps({'items': items, 'last_updated': None, 'stats': {}}))
    return NewsStore(path)


def _items(count, category='crypto'):
    return [
        {
            'id': f'{category}-{n}',
            'title': f'Headline number {n}',
            'summary': '',
            'category': category,
            'relevance_score': None,
            'tier': None,
        }
        for n in range(count)
    ]


def test_a_backlog_larger_than_a_page_is_scored_in_full(tmp_path):
    """get_unscored_items() used to default to 50 while the feeds added 120-260
    a day: a pass capped at a page can only fall further behind."""
    store = _store(tmp_path, _items(260))

    result = F.score_unscored_items(store)

    assert result['scored'] == 260
    assert result['stats']['unscored'] == 0
    assert all(i['relevance_score'] is not None for i in store.get_all_items())


def test_every_scored_item_records_when_it_was_scored(tmp_path):
    """No item in the live store had ever carried scored_at, which is what made
    the missing pass invisible."""
    store = _store(tmp_path, _items(3))

    F.score_unscored_items(store)

    assert all(i.get('scored_at') for i in store.get_all_items())


def test_items_already_scored_are_left_alone(tmp_path):
    store = _store(tmp_path, [
        {'id': 'done', 'title': 'Old news', 'category': 'crypto',
         'relevance_score': 12, 'tier': 'low', 'scored_at': '2026-09-01T00:00:00+00:00'},
        {'id': 'fresh', 'title': 'New news', 'category': 'crypto', 'relevance_score': None},
    ])

    result = F.score_unscored_items(store)

    assert result['scored'] == 1
    assert store.get_item_by_id('done')['relevance_score'] == 12
    assert store.get_item_by_id('done')['scored_at'] == '2026-09-01T00:00:00+00:00'


def test_a_second_pass_over_the_same_store_changes_nothing(tmp_path):
    store = _store(tmp_path, _items(5))

    F.score_unscored_items(store)
    before = [(i['id'], i['relevance_score'], i['tier']) for i in store.get_all_items()]

    assert F.score_unscored_items(store)['scored'] == 0
    assert [(i['id'], i['relevance_score'], i['tier']) for i in store.get_all_items()] == before


def test_the_tiers_the_fetcher_prints_are_the_tiers_on_disk(tmp_path):
    """The fetcher's output block reports Unscored/High/Medium/Low from these
    stats; they printed zeroes for as long as nothing wrote a score."""
    store = _store(tmp_path, _items(4, 'crypto') + _items(4, 'geopolitics'))

    stats = F.score_unscored_items(store)['stats']

    assert stats['high_tier'] == 4
    assert stats['medium_tier'] == 4
    assert stats['unscored'] == 0


def test_a_scorer_failure_leaves_the_fetch_successful(tmp_path, monkeypatch):
    """Fetching is the part that cannot be redone later -- an item missed while
    a feed was reachable is gone. Items are on disk before scoring runs, so a
    scorer fault costs a scoring pass and nothing else."""
    monkeypatch.setattr(F, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(F, 'HEADLINES_FILE', tmp_path / "headlines.json")
    monkeypatch.setattr(F, 'PROCESSED_FILE', tmp_path / ".processed_items.json")
    monkeypatch.setattr(F, 'load_feeds_config', lambda: {'feeds': []})
    monkeypatch.setattr(F, 'fetch_all_feeds', lambda config, processed: [
        {'id': 'x1', 'title': 'A headline', 'summary': '', 'category': 'crypto'},
    ])

    def _explode(store=None):
        raise RuntimeError("relevance source is on fire")

    monkeypatch.setattr(F, 'score_unscored_items', _explode)

    result = F.fetch_and_store()

    assert result['status'] == 'success'
    assert result['new_items_count'] == 1
    assert result['scoring_status'] == 'error'
    assert result['scored_count'] == 0

    stored = json.loads((tmp_path / "headlines.json").read_text())
    assert [i['id'] for i in stored['items']] == ['x1']
    assert stored['items'][0]['relevance_score'] is None


def test_a_fetch_scores_what_it_just_fetched(tmp_path, monkeypatch):
    monkeypatch.setattr(F, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(F, 'HEADLINES_FILE', tmp_path / "headlines.json")
    monkeypatch.setattr(F, 'PROCESSED_FILE', tmp_path / ".processed_items.json")
    monkeypatch.setattr(F, 'load_feeds_config', lambda: {'feeds': []})
    monkeypatch.setattr(F, 'fetch_all_feeds', lambda config, processed: [
        {'id': 'x1', 'title': 'A crypto headline', 'summary': '', 'category': 'crypto'},
        {'id': 'x2', 'title': 'A world headline', 'summary': '', 'category': 'geopolitics'},
    ])
    # The real pass, aimed at the throwaway store: NewsStore binds its default
    # path at import, so redirecting the module constant would not reach it.
    real_pass = F.score_unscored_items
    monkeypatch.setattr(
        F, 'score_unscored_items',
        lambda store=None: real_pass(NewsStore(tmp_path / "headlines.json")),
    )

    result = F.fetch_and_store()

    assert result['scoring_status'] == 'success'
    assert result['scored_count'] == 2
    assert result['stats']['unscored'] == 0


def test_the_shipped_relevance_sources_load(tmp_path):
    """A guard on the paths themselves: the tag registry moved once already
    (commands/news.md still names .datacore/config/tags.yaml), and a source that
    quietly resolves to nothing degrades to base scores with no complaint."""
    sources = S.load_relevance_sources()
    assert sources.keywords is not None
