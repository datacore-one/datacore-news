"""The scoring rules of commands/news.md Step 4, as arithmetic anyone can check.

Until 2026-09-21 these rules existed only as prose for an agent to run by hand;
nothing scheduled it, and the store held 500 items with 0 scored. Prose cannot
be tested, so the first job of this suite is that the rules now have a value.
"""
import sys
from pathlib import Path

import pytest
import yaml

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import news_scorer as S  # noqa: E402


@pytest.fixture
def sources():
    """The three relevance sources, with terms chosen to expose the rules."""
    return S.RelevanceSources(
        contacts=S.compile_terms(['Datafund', 'Ada Lovelace']),
        keywords=S.compile_terms(['solana', 'FOMC', 'interest rate']),
        demotions=S.compile_terms(['sponsored', 'meme coin']),
    )


def _write(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data))
    return path


class TestBaseScores:
    """Category alone decides where an item starts."""

    @pytest.mark.parametrize("category,expected", [
        ('crypto', 70),
        ('macro', 70),
        ('fed', 70),
        ('geopolitics', 50),
        ('ai-tech', 60),
        ('general', 40),
    ])
    def test_each_category_starts_at_its_documented_base(self, category, expected):
        assert S.score_content(category, 'Nothing here matches anything') == expected

    def test_an_unrecognised_category_scores_as_general(self):
        """A new feed with an unmapped category must still score, not crash or
        vanish: unknown is the same 40 as general."""
        assert S.score_content('sports-betting', 'A title') == 40
        assert S.score_content(None, 'A title') == 40
        assert S.score_content('', 'A title') == 40


class TestModifiers:
    """Each modifier, alone, against a known base."""

    def test_a_crm_contact_in_the_title_adds_fifteen(self, sources):
        assert S.score_content('geopolitics', 'Datafund signs data deal', sources=sources) == 65

    def test_a_contact_named_only_in_the_summary_does_not_count(self, sources):
        """Step 4 says "+15 if TITLE mentions a CRM contact" -- summaries are
        boilerplate-heavy, and counting them made the bonus near-universal."""
        assert S.score_content(
            'geopolitics', 'A border dispute', summary='Datafund was mentioned', sources=sources
        ) == 50

    def test_a_boost_keyword_adds_ten(self, sources):
        assert S.score_content('geopolitics', 'FOMC holds rates', sources=sources) == 60

    def test_a_boost_keyword_in_the_summary_counts(self, sources):
        assert S.score_content(
            'geopolitics', 'Central bank meets', summary='The FOMC held rates', sources=sources
        ) == 60

    def test_a_newsletter_item_adds_five_for_being_curated(self, sources):
        assert S.score_content('geopolitics', 'A headline', from_newsletter=True, sources=sources) == 55

    def test_a_demote_keyword_subtracts_ten(self, sources):
        assert S.score_content('crypto', 'Sponsored: buy this token', sources=sources) == 60

    def test_each_modifier_applies_once_however_many_terms_match(self, sources):
        """Step 4 reads "+10 if matches a boost keyword", not "+10 per keyword".
        Per-term accumulation would let one keyword-stuffed headline outrank
        every real story."""
        assert S.score_content(
            'geopolitics', 'FOMC, solana and the interest rate', sources=sources
        ) == 60

    def test_modifiers_stack_with_each_other(self, sources):
        # 50 base + 15 contact + 10 keyword + 5 newsletter - 10 demote
        assert S.score_content(
            'geopolitics',
            'Datafund on solana, sponsored',
            from_newsletter=True,
            sources=sources,
        ) == 70

    def test_markup_in_the_summary_is_not_matched_as_prose(self, sources):
        """RSS summaries arrive as HTML. Matching inside markup scores href
        values and attributes, which is not what the headline is about."""
        assert S.score_content(
            'geopolitics', 'A headline', summary='<a href="http://x/solana">Nothing</a>',
            sources=sources,
        ) == 50


class TestClamp:
    """A score is a 0-100 scale, whatever the modifiers add up to."""

    def test_every_modifier_at_once_reaches_exactly_one_hundred(self):
        sources = S.RelevanceSources(
            contacts=S.compile_terms(['Datafund']),
            keywords=S.compile_terms(['solana']),
        )
        assert S.score_content(
            'crypto', 'Datafund launches on solana', from_newsletter=True, sources=sources
        ) == 100

    def test_a_score_cannot_exceed_one_hundred(self):
        sources = S.RelevanceSources(
            contacts=S.compile_terms(['Datafund']),
            keywords=S.compile_terms(['solana']),
        )
        S.BASE_SCORES['test-ceiling'] = 100
        try:
            assert S.score_content(
                'test-ceiling', 'Datafund launches on solana', from_newsletter=True, sources=sources
            ) == 100
        finally:
            del S.BASE_SCORES['test-ceiling']

    def test_a_score_cannot_fall_below_zero(self):
        sources = S.RelevanceSources(demotions=S.compile_terms(['sponsored']))
        S.BASE_SCORES['test-floor'] = 5
        try:
            assert S.score_content('test-floor', 'Sponsored post', sources=sources) == 0
        finally:
            del S.BASE_SCORES['test-floor']


class TestWordBoundaries:
    """Substring matching is what silently inflates every score."""

    def test_fed_does_not_match_federal(self):
        """"Fed" inside "federal", "federation", "fedora" would fire on most
        macro prose and make the +10 meaningless."""
        pattern = S.compile_terms(['Fed'])
        assert pattern.search('The Fed holds rates')
        assert not pattern.search('A federal judge ruled')
        assert not pattern.search('The federation met')

    def test_ai_does_not_match_said_or_maintain(self):
        pattern = S.compile_terms(['AI'])
        assert pattern.search('AI models improve')
        assert pattern.search('The rise of ai')
        assert not pattern.search('He said nothing')
        assert not pattern.search('Plans to maintain output')

    def test_sol_does_not_match_solana_or_sold(self):
        pattern = S.compile_terms(['SOL'])
        assert pattern.search('SOL rallies 8%')
        assert not pattern.search('Solana TVL hits a high')
        assert not pattern.search('The stake was sold')

    def test_matching_ignores_case(self):
        pattern = S.compile_terms(['Solana'])
        assert pattern.search('SOLANA hits an all-time high')
        assert pattern.search('solana hits an all-time high')

    def test_a_multi_word_term_matches_as_a_phrase(self):
        pattern = S.compile_terms(['interest rate'])
        assert pattern.search('The interest rate decision')
        assert not pattern.search('Interest rates unchanged')

    def test_a_name_with_punctuation_matches_where_it_should(self):
        """CRM names are arbitrary strings. \\b flips meaning next to
        punctuation, so the boundary is written as lookarounds instead."""
        pattern = S.compile_terms(['ActProof (Advisa EOOD)'])
        assert pattern.search('ActProof (Advisa EOOD) raises a round')
        assert not pattern.search('ActProof (Advisa EOODX) raises a round')

    def test_no_terms_compiles_to_no_matcher(self):
        assert S.compile_terms([]) is None
        assert S.compile_terms(['', '  ']) is None


class TestTierBoundaries:
    """The tier edges are inclusive at exactly the threshold."""

    def test_seventy_is_high_and_sixty_nine_is_medium(self):
        assert S.tier_for(70) == 'high'
        assert S.tier_for(69) == 'medium'

    def test_forty_is_medium_and_thirty_nine_is_low(self):
        assert S.tier_for(40) == 'medium'
        assert S.tier_for(39) == 'low'

    def test_low_is_reachable_from_the_rules(self, sources):
        """No item in the live store lands low, which is a property of the feed
        mix and not of the matcher: the lowest configured base is geopolitics at
        50, and the only penalty is 10. An uncategorised newsletter item with a
        demote keyword is what low is for."""
        assert S.score_item(
            {'category': 'general', 'title': 'Sponsored roundup', 'from_newsletter': True},
            sources,
        ) == (35, 'low')

    def test_the_extremes_land_in_the_outer_tiers(self):
        assert S.tier_for(100) == 'high'
        assert S.tier_for(0) == 'low'

    def test_thresholds_come_from_module_settings_not_from_the_code(self, tmp_path):
        """module.yaml exposes high_tier_threshold and medium_tier_threshold;
        hardcoding 70/40 would make those settings a lie."""
        manifest = _write(tmp_path / "module.yaml", {
            'settings': {
                'high_tier_threshold': {'default': 85},
                'medium_tier_threshold': {'default': 55},
            }
        })
        high, medium = S.load_thresholds(manifest)
        assert (high, medium) == (85, 55)
        assert S.tier_for(84, high, medium) == 'medium'
        assert S.tier_for(85, high, medium) == 'high'

    def test_the_shipped_manifest_carries_the_documented_thresholds(self):
        assert S.load_thresholds() == (70, 40)

    def test_unreadable_settings_fall_back_to_the_documented_thresholds(self, tmp_path):
        broken = tmp_path / "module.yaml"
        broken.write_text("settings: {high_tier_threshold: {default: 'not a number'}}")
        assert S.load_thresholds(broken) == (70, 40)
        assert S.load_thresholds(tmp_path / "absent.yaml") == (70, 40)


class TestMissingSources:
    """Every relevance source is optional; none of them may take the pass down."""

    def test_absent_source_files_leave_the_base_score_intact(self, tmp_path):
        sources = S.load_relevance_sources(
            crm_path=tmp_path / "no-contacts.yaml",
            tags_paths=(tmp_path / "no-tags.yaml",),
            feeds_path=tmp_path / "no-feeds.yaml",
        )
        assert (sources.contacts, sources.keywords, sources.demotions) == (None, None, None)
        assert S.score_content('crypto', 'Datafund launches on solana', sources=sources) == 70

    def test_a_malformed_source_file_is_a_warning_not_a_crash(self, tmp_path):
        broken = tmp_path / "contacts-index.yaml"
        broken.write_text("contacts: [ this is not: valid: yaml")
        sources = S.load_relevance_sources(
            crm_path=broken,
            tags_paths=(tmp_path / "absent.yaml",),
            feeds_path=_write(tmp_path / "feeds.yaml", {'boost_keywords': ['solana']}),
        )
        assert sources.contacts is None
        assert S.score_content('crypto', 'solana rallies', sources=sources) == 80

    def test_scoring_with_no_sources_at_all_is_the_base_score(self):
        assert S.score_content('ai-tech', 'Datafund ships solana FOMC sponsored') == 60

    def test_contact_name_fragments_are_not_matched(self, tmp_path):
        """The CRM index is compiled from reference filenames and carries
        artifacts -- "S", "an", bare digits. Measured 2026-09-21, those alone
        matched 257 of the 500 stored titles; every one of them was noise."""
        crm = _write(tmp_path / "contacts-index.yaml", {'contacts': [
            {'name': 'S', 'type': 'person'},
            {'name': 'an', 'type': 'person'},
            {'name': '1000228277', 'type': 'person'},
            {'name': 'Datafund', 'type': 'company'},
        ]})
        assert S.load_contact_names(crm) == ['Datafund']

    def test_tag_terms_join_the_boost_keyword_bucket(self, tmp_path):
        """Step 3 calls the tag registry a relevance booster; Step 4 gives it no
        modifier of its own, so a tag match is worth the same +10 as a keyword
        -- and matching both still adds 10, not 20."""
        sources = S.load_relevance_sources(
            crm_path=tmp_path / "absent.yaml",
            tags_paths=(_write(tmp_path / "tags.yaml", {'domains': {'defi': {'org': ':defi:'}}}),),
            feeds_path=_write(tmp_path / "feeds.yaml", {'boost_keywords': ['solana']}),
        )
        assert S.score_content('geopolitics', 'A defi protocol launches', sources=sources) == 60
        assert S.score_content('geopolitics', 'A defi protocol on solana', sources=sources) == 60


class TestIdempotency:
    """Rescoring is safe, because scoring reads content and never a prior score."""

    def test_rescoring_the_same_item_does_not_compound_modifiers(self, sources):
        item = {
            'id': 'abc',
            'category': 'crypto',
            'title': 'Datafund launches on solana',
            'summary': '',
            'from_newsletter': True,
        }
        first = S.score_item(item, sources)
        assert first == (100, 'high')
        for _ in range(5):
            assert S.score_item(item, sources) == first

    def test_an_item_already_carrying_a_score_is_scored_from_its_content(self, sources):
        """An item rescored after a store round-trip must not read its own
        previous relevance_score back in as an input."""
        item = {
            'id': 'abc',
            'category': 'geopolitics',
            'title': 'A border dispute',
            'relevance_score': 95,
            'tier': 'high',
        }
        assert S.score_item(item, sources) == (50, 'medium')
