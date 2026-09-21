#!/usr/bin/env python3
"""
Relevance scoring for News Module.

Implements commands/news.md Step 3 (relevance sources) and Step 4 (base score,
modifiers, tiers). The rules are arithmetic, so this is deterministic and needs
no model call: the same item scores the same on every run.

Everything here is a pure function -- content in, score and tier out. Nothing
touches the store or the network, so the rules are testable on their own.

Usage:
    from news_scorer import load_relevance_sources, load_thresholds, score_item

    sources = load_relevance_sources()
    high, medium = load_thresholds()
    score, tier = score_item(item, sources, high, medium)
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

try:
    import yaml
except ImportError:  # scoring degrades to base scores rather than failing
    yaml = None

logger = logging.getLogger(__name__)

MODULE_DIR = Path(__file__).resolve().parent.parent
DATACORE_DIR = MODULE_DIR.parent.parent

# commands/news.md names .datacore/config/tags.yaml; the registry this
# installation actually keeps is .datacore/tags.yaml. Try the documented path
# first, then the real one, and score off base alone if neither is there.
TAGS_FILES = (DATACORE_DIR / "config" / "tags.yaml", DATACORE_DIR / "tags.yaml")
CRM_CONTACTS_FILE = DATACORE_DIR / "state" / "crm" / "contacts-index.yaml"
FEEDS_FILE = MODULE_DIR / "data" / "feeds.local.yaml"
MODULE_MANIFEST = MODULE_DIR / "module.yaml"

# Base score by feed category (commands/news.md Step 4).
BASE_SCORES = {
    'crypto': 70,
    'macro': 70,
    'fed': 70,
    'geopolitics': 50,
    'ai-tech': 60,
    'general': 40,
}
UNKNOWN_CATEGORY_SCORE = BASE_SCORES['general']

CRM_BONUS = 15
KEYWORD_BONUS = 10
NEWSLETTER_BONUS = 5
DEMOTE_PENALTY = 10

SCORE_MIN = 0
SCORE_MAX = 100

DEFAULT_HIGH_THRESHOLD = 70
DEFAULT_MEDIUM_THRESHOLD = 40

# The CRM index is compiled from reference filenames, so it carries artifacts
# alongside real entities: single letters ("S"), fragments ("an"), bare digits.
# Measured 2026-09-21 against the 500 items then in the store, those artifacts
# alone matched 257 titles; dropping names under four characters took it to 153.
MIN_CONTACT_NAME_LENGTH = 4

# Single common words that are also legitimate CRM entries. "Meta" really is a
# company and "Michael" really is someone's note, so the fix cannot be to
# delete them from the CRM — but a headline containing the bare word "world"
# or "bank" is not evidence that this entity was mentioned, and awarding the
# contact bonus for it makes the tier meaningless. A MULTI-WORD name
# ("Meta Platforms") is specific enough to keep, so only the bare token is
# refused; anything with a space passes regardless.
GENERIC_CONTACT_WORDS = frozenset({
    'bank', 'world', 'crypto', 'meta', 'will', 'data', 'group', 'capital',
    'michael', 'david', 'alex', 'john', 'labs', 'research', 'news', 'media',
})

_HTML_TAG = re.compile(r'<[^>]+>')


def strip_html(text: str) -> str:
    """Drop markup so keywords match prose, not href values and attributes."""
    if not text:
        return ''
    return _HTML_TAG.sub(' ', text)


def compile_terms(terms: Iterable[str]) -> Optional[re.Pattern]:
    """Compile terms into one case-insensitive, word-bounded matcher.

    Substring matching would make "AI" fire on "said" and "Fed" on "federal",
    which inflates every score and leaves the tiers meaningless. The boundary is
    written as lookarounds rather than \\b because terms are arbitrary strings:
    \\b flips meaning next to punctuation, so a contact like "ActProof (Advisa)"
    would match in places it should not.
    """
    unique = {t.strip() for t in terms if t and t.strip()}
    if not unique:
        return None

    # Longest first so the alternation reports the most specific match.
    ordered = sorted(unique, key=len, reverse=True)
    pattern = '|'.join(r'(?<!\w)' + re.escape(t) + r'(?!\w)' for t in ordered)
    return re.compile(pattern, re.IGNORECASE)


@dataclass
class RelevanceSources:
    """Compiled matchers for the three optional relevance sources."""

    contacts: Optional[re.Pattern] = None
    keywords: Optional[re.Pattern] = None
    demotions: Optional[re.Pattern] = None

    def mentions_contact(self, text: str) -> bool:
        return bool(self.contacts and text and self.contacts.search(text))

    def matches_keyword(self, text: str) -> bool:
        return bool(self.keywords and text and self.keywords.search(text))

    def matches_demotion(self, text: str) -> bool:
        return bool(self.demotions and text and self.demotions.search(text))


def _read_yaml(path: Path) -> dict:
    """Read a YAML mapping, returning {} for anything unreadable.

    Every relevance source is optional: a missing or malformed file costs the
    modifier it would have supplied, never the scoring pass.
    """
    if yaml is None or not path or not Path(path).exists():
        return {}
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Could not read relevance source {path}: {e}")
        return {}


def load_contact_names(crm_path: Path = CRM_CONTACTS_FILE) -> list:
    """Names of CRM people, companies and organisations worth matching on."""
    contacts = _read_yaml(crm_path).get('contacts') or []
    names = []
    for contact in contacts:
        if not isinstance(contact, dict):
            continue
        name = (contact.get('name') or '').strip()
        if len(name) < MIN_CONTACT_NAME_LENGTH or name.isdigit():
            continue
        if ' ' not in name and name.lower() in GENERIC_CONTACT_WORDS:
            continue
        names.append(name)
    return names


def load_tag_terms(tags_paths: Sequence[Path] = TAGS_FILES) -> list:
    """Work-area terms from the tag registry (Step 3 'Tags')."""
    for path in tags_paths:
        domains = _read_yaml(path).get('domains')
        if isinstance(domains, dict):
            return [str(term) for term in domains.keys()]
    return []


def load_relevance_sources(
    crm_path: Path = CRM_CONTACTS_FILE,
    tags_paths: Sequence[Path] = TAGS_FILES,
    feeds_path: Path = FEEDS_FILE,
) -> RelevanceSources:
    """Load and compile the relevance sources named in commands/news.md Step 3."""
    feeds = _read_yaml(feeds_path)

    # Step 3 calls the tag registry a relevance booster but Step 4 gives it no
    # modifier of its own, so its terms join the boost-keyword bucket: an item
    # matching a tag and a keyword still takes +10 once, not +20.
    keywords = list(feeds.get('boost_keywords') or []) + load_tag_terms(tags_paths)

    return RelevanceSources(
        contacts=compile_terms(load_contact_names(crm_path)),
        keywords=compile_terms(keywords),
        demotions=compile_terms(feeds.get('demote_keywords') or []),
    )


def load_thresholds(manifest_path: Path = MODULE_MANIFEST) -> tuple:
    """Tier thresholds from module.yaml settings, falling back to the spec's."""
    settings = _read_yaml(manifest_path).get('settings') or {}

    def _threshold(key: str, fallback: int) -> int:
        setting = settings.get(key)
        value = setting.get('default') if isinstance(setting, dict) else setting
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    return (
        _threshold('high_tier_threshold', DEFAULT_HIGH_THRESHOLD),
        _threshold('medium_tier_threshold', DEFAULT_MEDIUM_THRESHOLD),
    )


def base_score(category: Optional[str]) -> int:
    """Base score for a feed category; unknown categories score as general."""
    if not category:
        return UNKNOWN_CATEGORY_SCORE
    return BASE_SCORES.get(str(category).strip().lower(), UNKNOWN_CATEGORY_SCORE)


def tier_for(
    score: int,
    high_threshold: int = DEFAULT_HIGH_THRESHOLD,
    medium_threshold: int = DEFAULT_MEDIUM_THRESHOLD,
) -> str:
    """Tier for a score: >= high is high, >= medium is medium, else low."""
    if score >= high_threshold:
        return 'high'
    if score >= medium_threshold:
        return 'medium'
    return 'low'


def score_content(
    category: Optional[str],
    title: str,
    summary: str = '',
    from_newsletter: bool = False,
    sources: Optional[RelevanceSources] = None,
) -> int:
    """Relevance score (0-100) for one item's content.

    Each modifier applies at most once, however many terms match: Step 4 reads
    "+10 if matches a boost keyword", not "+10 per keyword". Applying once also
    keeps the pass idempotent -- rescoring the same content cannot compound.
    """
    sources = sources or RelevanceSources()
    title = title or ''

    # Contacts are matched against the title only ("+15 if title mentions a CRM
    # contact"); keywords get the summary prose too, where the substance of a
    # headline usually is.
    keyword_text = f"{title} {strip_html(summary)}"

    score = base_score(category)

    if sources.mentions_contact(title):
        score += CRM_BONUS
    if sources.matches_keyword(keyword_text):
        score += KEYWORD_BONUS
    if from_newsletter:
        score += NEWSLETTER_BONUS
    if sources.matches_demotion(keyword_text):
        score -= DEMOTE_PENALTY

    return max(SCORE_MIN, min(SCORE_MAX, score))


def score_item(
    item: dict,
    sources: Optional[RelevanceSources] = None,
    high_threshold: int = DEFAULT_HIGH_THRESHOLD,
    medium_threshold: int = DEFAULT_MEDIUM_THRESHOLD,
) -> tuple:
    """Score a stored news item, returning (score, tier)."""
    score = score_content(
        category=item.get('category'),
        title=item.get('title', ''),
        summary=item.get('summary', ''),
        from_newsletter=bool(item.get('from_newsletter')),
        sources=sources,
    )
    return score, tier_for(score, high_threshold, medium_threshold)


if __name__ == "__main__":
    sources = load_relevance_sources()
    high, medium = load_thresholds()
    print(f"Thresholds: high >= {high}, medium >= {medium}")
    for name, pattern in (
        ('CRM contacts', sources.contacts),
        ('Boost keywords + tags', sources.keywords),
        ('Demote keywords', sources.demotions),
    ):
        print(f"{name}: {'loaded' if pattern else 'unavailable'}")
