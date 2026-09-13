import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import feed_fetcher as feeds
from news_context import context
from news_store import NewsStore
import newsletter_integration as newsletters


@pytest.fixture
def news(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    space = root / 'named'
    (space / '.datacore').mkdir(parents=True)
    (space / '.datacore/config.yaml').write_text('space: {name: self, type: personal}\n')
    monkeypatch.setenv('DATACORE_ROOT', str(root))
    monkeypatch.delenv('DATACORE_SPACE', raising=False)
    monkeypatch.setattr(feeds, 'load_feeds_config', lambda: {'feeds': [{'name': 'fixture', 'url': 'https://example.invalid/rss'}]})
    return context()


def test_actual_feed_parser_uses_bounded_download_and_retry_preserves_annotations(news, monkeypatch):
    raw = b'''<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>Fixture</title>
    <link>https://example.invalid</link><description>Fixture</description><item><title>Retained</title>
    <link>https://example.invalid/item</link><guid>fixture-id</guid></item></channel></rss>'''
    requests = []
    def download(url, *, max_bytes):
        requests.append((url, max_bytes))
        return raw
    monkeypatch.setattr(feeds, 'download', download)
    assert feeds.fetch_and_store()['new_items_count'] == 1
    store = NewsStore()
    item = store.get_all_items()[0]
    store.update_score(item['id'], 95, 'high', 'retained annotation')
    assert feeds.fetch_and_store()['new_items_count'] == 0
    assert store.get_item_by_id(item['id'])['summary_ai'] == 'retained annotation'
    assert requests == [('https://example.invalid/rss', 4 * 1024**2)] * 2


def test_processed_ack_failure_retries_without_losing_or_duplicating_news(news, monkeypatch):
    monkeypatch.setattr(feeds, 'fetch_all_feeds', lambda *a: [{'id': 'new', 'title': 'New', 'link': 'https://example.invalid/new'}])
    write = feeds.save_processed_items
    def fail(_):
        raise OSError('injected acknowledgement interruption')
    monkeypatch.setattr(feeds, 'save_processed_items', fail)
    with pytest.raises(OSError):
        feeds.fetch_and_store()
    assert len(NewsStore().get_all_items()) == 1
    monkeypatch.setattr(feeds, 'save_processed_items', write)
    assert feeds.fetch_and_store()['new_items_count'] == 0
    assert len(NewsStore().get_all_items()) == 1
    assert feeds.load_processed_items() == {'new'}


def test_corrupt_history_cannot_be_reset_or_acknowledged(news, monkeypatch):
    target = news.data / '.processed_items.json'
    target.write_text('{"processed_ids":')
    monkeypatch.setattr(feeds, 'fetch_all_feeds', lambda *a: pytest.fail('fetched before verifying retained state'))
    with pytest.raises(ValueError):
        feeds.fetch_and_store()
    assert target.read_text() == '{"processed_ids":'


def test_fetch_cannot_silently_trim_existing_annotated_news(news, monkeypatch):
    NewsStore().add_items([{'id': str(n), 'title': 'Retained', 'summary_ai': 'retained note'} for n in range(501)])
    monkeypatch.setattr(feeds, 'fetch_all_feeds', lambda *a: [{'id': 'new', 'title': 'New'}])
    assert feeds.fetch_and_store()['total_items'] == 502
    assert len([i for i in NewsStore().get_all_items() if i.get('summary_ai')]) == 501


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://127.0.0.1/private', 'http://[::1]/private'])
def test_feed_fetch_cannot_access_local_files_or_services(url):
    with pytest.raises(ValueError, match='retrieval'):
        feeds.parse_feed({'name': 'fixture', 'url': url})


def test_newsletter_retries_keep_existing_scores_and_use_selected_inbox(news, tmp_path):
    (news.space / 'org').mkdir()
    inbox = news.space / 'org/inbox.org'
    inbox.write_text('* TODO Read [[https://example.invalid/article][Article]] :research:\n')
    assert newsletters.find_inbox_file() == inbox
    entries = newsletters.extract_newsletter_urls(newsletters.read_inbox_items(inbox))
    assert newsletters.add_to_news_queue(entries)['added'] == 1
    store = NewsStore()
    identity = store.get_all_items()[0]['id']
    store.update_score(identity, 90, 'high')
    assert newsletters.add_to_news_queue(entries)['added'] == 0
    assert store.get_item_by_id(identity)['relevance_score'] == 90
    # The caller cannot substitute an external inbox after the discovery probe.
    outside = tmp_path / 'unrelated-inbox'
    outside.write_text(inbox.read_text())
    with pytest.raises(ValueError):
        newsletters.read_inbox_items(outside)
