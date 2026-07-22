"""Tests for translation fallback, bus protocol handlers, and matching -
mirrors ovos-skill-ovosblog's test suite (same design, second real-world
test of the pattern)."""
from unittest.mock import MagicMock

from conftest import COMMON_READING_SEARCH_RESPONSE, COMMON_READING_FETCH_CONTENT_RESPONSE, COMMON_READING_PONG


def make_message(data=None):
    m = MagicMock()
    m.data = data or {}
    m.reply = MagicMock(side_effect=lambda mtype, d: MagicMock(msg_type=mtype, data=d))
    return m


def _sample_index():
    return {
        "https://arxiv.org/abs/1": {"title": "Rater State Bias", "author": "Alice",
                                     "abstract": "Abstract A.", "pubdate": "Mon, 01 Jan 2024 00:00:00 -0400"},
        "https://arxiv.org/abs/2": {"title": "New Optimizer", "author": "Bob",
                                     "abstract": "Abstract B.", "pubdate": "Wed, 01 Jan 2025 00:00:00 -0400"},
    }


def test_handle_search_matches_by_phrase(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "rater state bias"}))
    sent = skill.bus.emit.call_args[0][0]
    assert sent.msg_type == COMMON_READING_SEARCH_RESPONSE
    assert sent.data["content_id"] == "https://arxiv.org/abs/1"
    assert sent.data["author"] == "Alice"
    assert sent.data["source"] == "arxiv.org"
    assert sent.data["collection"] == "arXiv (cs.AI)"
    assert sent.data["machine_translated"] is False


def test_handle_search_surprise_me_picks_latest(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": None, "collection_hint": "arxiv"}))
    sent = skill.bus.emit.call_args[0][0]
    assert sent.data["content_id"] == "https://arxiv.org/abs/2"


def test_handle_search_stays_silent_for_unmatched_collection(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "rater state bias", "collection_hint": "grimm"}))
    skill.bus.emit.assert_not_called()


def test_handle_search_stays_silent_for_mismatched_content_type(skill):
    skill.index = _sample_index()
    skill.handle_search(make_message({"phrase": "rater state bias", "content_type": "story"}))
    skill.bus.emit.assert_not_called()


def test_handle_search_responds_for_matching_content_type(skill):
    skill.index = _sample_index()
    for content_type in ["paper", "abstract", "research", "study"]:
        skill.bus.emit.reset_mock()
        skill.handle_search(make_message({"phrase": "rater state bias", "content_type": content_type}))
        skill.bus.emit.assert_called_once()


def test_handle_fetch_content_returns_abstract_as_single_paragraph(skill):
    skill.index = _sample_index()
    skill.handle_fetch_content(make_message({"content_id": "https://arxiv.org/abs/1"}))
    sent = skill.bus.emit.call_args[0][0]
    assert sent.msg_type == COMMON_READING_FETCH_CONTENT_RESPONSE
    assert sent.data["paragraphs"] == ["Abstract A."]


def test_handle_fetch_content_unknown_id_returns_empty(skill):
    skill.index = {}
    skill.handle_fetch_content(make_message({"content_id": "nonexistent"}))
    sent = skill.bus.emit.call_args[0][0]
    assert sent.data["paragraphs"] == []


def test_non_english_matches_against_translated_titles(skill, monkeypatch):
    from conftest import ArxivPapers
    monkeypatch.setattr(ArxivPapers, "lang", "da-dk", raising=False)
    skill.index = _sample_index()
    fake_translator = MagicMock()
    translations = {"Rater State Bias": "Bedømmer-tilstandsbias", "New Optimizer": "Ny optimering"}
    fake_translator.translate.side_effect = lambda text, target, source: translations[text]
    skill._get_translator = MagicMock(return_value=fake_translator)

    skill.handle_search(make_message({"phrase": "bedømmer-tilstandsbias"}))

    sent = skill.bus.emit.call_args[0][0]
    assert sent.data["content_id"] == "https://arxiv.org/abs/1"
    assert sent.data["machine_translated"] is True


def test_non_english_without_translator_stays_silent(skill, monkeypatch):
    from conftest import ArxivPapers
    monkeypatch.setattr(ArxivPapers, "lang", "da-dk", raising=False)
    skill.index = _sample_index()
    skill._get_translator = MagicMock(return_value=None)

    skill.handle_search(make_message({"phrase": "bedømmer-tilstandsbias"}))

    skill.bus.emit.assert_not_called()


def test_handle_ping_replies_with_pong(skill):
    skill.handle_ping(make_message())

    sent = skill.bus.emit.call_args[0][0]
    assert sent.msg_type == COMMON_READING_PONG
    assert sent.data["skill_id"] == skill.skill_id
    assert sent.data["collection"] == "arXiv"


def test_handle_ping_does_not_touch_the_index(skill):
    skill.index = None

    skill.handle_ping(make_message())

    skill.bus.emit.assert_called_once()
