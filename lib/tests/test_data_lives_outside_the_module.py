"""MEM-63: the news module keeps no user data inside itself.

Headlines, the processed-item ledger and the personal feed/theme lists live in
the selected space's private module-data folder, resolved through the core
module_context helper -- never in the installed module's own data/ directory.
"""
import json
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
MODULE = LIB.parent
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(MODULE.parents[1] / "lib"))

import news_paths  # noqa: E402


@pytest.fixture
def install(tmp_path, monkeypatch):
    root = tmp_path / "Data"
    space = root / "0-personal"
    (space / ".datacore").mkdir(parents=True)
    (space / ".datacore/config.yaml").write_text("space: {name: personal, type: personal}\n")
    monkeypatch.setenv("DATACORE_ROOT", str(root))
    monkeypatch.delenv("DATACORE_SPACE", raising=False)
    return root, space


def test_data_resolves_to_the_private_space_folder(install):
    _, space = install
    data = news_paths.data_dir()
    # A private folder of the space (module-data/, or the space's own scoped
    # modules/ folder on a fresh install) -- never the installed module.
    assert data.is_relative_to(space / ".datacore") and not data.is_relative_to(MODULE)
    assert data.name == "data" and data.parent.name == "news"
    assert data.is_dir() and data.stat().st_mode & 0o077 == 0


def test_a_second_personal_space_does_not_make_the_store_ambiguous(install):
    root, space = install
    other = root / "9-practice/.datacore"
    other.mkdir(parents=True)
    (other / "config.yaml").write_text("space: {name: practice, type: personal}\n")
    assert news_paths.data_dir().is_relative_to(space)


def test_the_fetcher_writes_headlines_into_the_private_folder(install, monkeypatch):
    import feed_fetcher as F
    _, space = install
    for name in ("DATA_DIR", "HEADLINES_FILE", "PROCESSED_FILE", "FEEDS_FILE"):
        monkeypatch.setattr(F, name, None)
    monkeypatch.setattr(F, "fetch_all_feeds", lambda config, processed: [
        {"id": "x1", "title": "A headline", "summary": "", "category": "crypto"}])
    monkeypatch.setattr(F, "score_unscored_items", lambda store=None: {"status": "skipped", "scored": 0, "stats": {}})
    F.fetch_and_store()
    data = news_paths.data_dir()
    assert [i["id"] for i in json.loads((data / "headlines.json").read_text())["items"]] == ["x1"]
    assert (data / ".processed_items.json").exists()


def test_examples_ship_outside_data():
    assert (MODULE / "examples/feeds.example.yaml").is_file()
    assert (MODULE / "examples/tracked_themes.example.yaml").is_file()
