"""Actual retained state must survive stale readers and failed writes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import news_store


@pytest.fixture
def stored(tmp_path):
    path = tmp_path / 'headlines.json'
    path.write_text(json.dumps({'metadata': 'retained', 'items': [
        {'id': 'a', 'title': 'First', 'relevance_score': None},
        {'id': 'b', 'title': 'Second', 'relevance_score': None}]}))
    return path


def test_stale_scorer_cannot_erase_another_completed_score(stored):
    first, second = news_store.NewsStore(stored), news_store.NewsStore(stored)
    first.get_all_items()
    second.get_all_items()
    assert first.update_score('a', 80, 'high')
    assert second.update_score('b', 60, 'medium')
    data = json.loads(stored.read_text())
    assert [item['relevance_score'] for item in data['items']] == [80, 60]
    assert data['metadata'] == 'retained'


@pytest.mark.parametrize('bad', ['{"items": [', 'null', '{"items":{},"items":[]}'])
def test_malformed_existing_store_is_not_reported_as_empty(stored, bad):
    stored.write_text(bad)
    with pytest.raises(ValueError):
        news_store.NewsStore(stored).get_all_items()
    assert stored.read_text() == bad


def test_interrupted_serialization_cannot_truncate_existing_store(stored, monkeypatch):
    original = stored.read_bytes()
    def partial(value, output, **kwargs):
        output.write('{"partial":')
        raise OSError('injected interrupted serialization')
    # Old writer streams straight onto the authoritative target. New writers
    # may serialize in memory; also inject the shared publication flush failure.
    monkeypatch.setattr(news_store.json, 'dump', partial)
    import file_utils
    def fail(fd):
        raise OSError('injected flush failure')
    monkeypatch.setattr(file_utils.os, 'fsync', fail)
    with pytest.raises(OSError):
        news_store.NewsStore(stored).update_score('a', 80, 'high')
    assert stored.read_bytes() == original


def test_default_store_uses_declared_space_instead_of_installed_code(tmp_path):
    root = tmp_path / 'selected'
    config = root / 'named/.datacore/config.yaml'
    config.parent.mkdir(parents=True)
    config.write_text('space: {name: self, type: personal}\n')
    data = root / 'named/.datacore/module-data/news/data'
    data.mkdir(parents=True, mode=0o700)
    data.parent.chmod(0o700)
    data.parent.parent.chmod(0o700)
    (data / 'headlines.json').write_text('{"items":[{"id":"retained","title":"Retained"}]}')
    code = tmp_path / 'immutable-code/lib'
    code.mkdir(parents=True)
    source = Path(news_store.__file__).parent
    for name in ('news_store.py', 'news_context.py'):
        if (source / name).exists():
            (code / name).write_bytes((source / name).read_bytes())
    script = ('import sys,json;sys.path.insert(0,sys.argv[1]);'
              'from news_store import NewsStore;print(json.dumps(NewsStore().get_all_items()))')
    result = subprocess.run([sys.executable, '-I', '-c', script, str(code)],
                            capture_output=True, text=True, timeout=10,
                            env=dict(os.environ, DATACORE_ROOT=str(root)))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]['id'] == 'retained'
    assert not (code.parent / 'data').exists()


def test_retried_fetch_cannot_erase_scores_or_duplicate_identical_urls(stored):
    store = news_store.NewsStore(stored)
    assert store.update_score('a', 90, 'high', 'preserve annotation')
    assert store.add_items([{'id': 'a', 'title': 'stale', 'relevance_score': None}]) == 0
    assert store.add_items([{'id': 'c', 'title': 'New', 'link': 'https://example.invalid/new'}]) == 1
    assert store.add_items([{'id': 'different-hash', 'title': 'New', 'link': 'https://example.invalid/new'}]) == 0
    current = store.get_item_by_id('a')
    assert current['relevance_score'] == 90
    assert current['summary_ai'] == 'preserve annotation'
    assert len(store.get_all_items()) == 3


def test_snapshot_compatibility_writer_refuses_stale_replace(stored):
    stale, fresh = news_store.NewsStore(stored), news_store.NewsStore(stored)
    stale._load()['items'][0]['title'] = 'stale edit'
    fresh.update_score('b', 80, 'high')
    original = stored.read_bytes()
    with pytest.raises(ValueError, match='changed'):
        stale._save()
    assert stored.read_bytes() == original


def test_real_concurrent_scorers_preserve_each_others_updates(stored):
    script = ('import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
              'from news_store import NewsStore;'
              'assert NewsStore(Path(sys.argv[2])).update_score(sys.argv[3],80,"high")')
    children = [subprocess.Popen([sys.executable, '-I', '-c', script, str(Path(news_store.__file__).parent),
                                 str(stored), identity], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for identity in ('a', 'b')]
    for child in children:
        _, error = child.communicate(timeout=15)
        assert child.returncode == 0, error
    assert [item['relevance_score'] for item in json.loads(stored.read_text())['items']] == [80, 80]


def test_retention_archives_every_removed_annotation_before_deletion(stored):
    store = news_store.NewsStore(stored)
    store.update_score('a', 90, 'high', 'preserve annotation')
    before = store.get_all_items()
    assert store.cleanup_old_items(max_items=0) == 2
    assert store.get_all_items() == []
    archives = list((stored.parent / 'archive').glob('*.json'))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text())['items'] == before


def test_archive_flush_failure_does_not_remove_authoritative_items(stored, monkeypatch):
    def fail(*args):
        raise OSError('injected archive parent flush failure')
    monkeypatch.setattr(news_store, 'fsync_directory', fail)
    before = stored.read_bytes()
    with pytest.raises(OSError, match='flush failure'):
        news_store.NewsStore(stored).cleanup_old_items(max_items=0)
    assert stored.read_bytes() == before


def test_briefing_respects_requested_time_window(stored):
    from datetime import datetime, timedelta, timezone
    store = news_store.NewsStore(stored)
    store.add_items([{'id': 'recent', 'title': 'Recent', 'relevance_score': 80, 'tier': 'high',
                     'published': datetime.now(timezone.utc).isoformat()},
                    {'id': 'old', 'title': 'Old', 'relevance_score': 99, 'tier': 'high',
                     'published': (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}])
    assert [item['id'] for item in store.get_briefing_items(hours=24)['high']] == ['recent']


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo'])
def test_unsafe_state_cannot_be_read_or_replaced(stored, kind):
    original = stored.read_bytes()
    source = stored.with_name('original.json')
    stored.rename(source)
    if kind == 'symlink':
        stored.symlink_to(source)
    elif kind == 'hardlink':
        os.link(source, stored)
    else:
        os.mkfifo(stored)
    with pytest.raises((ValueError, OSError)):
        news_store.NewsStore(stored).update_score('a', 80, 'high')
    assert source.read_bytes() == original
