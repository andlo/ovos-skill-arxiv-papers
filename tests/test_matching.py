"""Tests for fuzzy collection_hint / content_type matching, and smoke
tests."""
import pytest
from conftest import ArxivPapers, FeedFetchError


def test_imports_cleanly():
    assert ArxivPapers is not None
    assert issubclass(FeedFetchError, Exception)


def test_is_an_ovos_skill():
    from ovos_workshop.skills import OVOSSkill
    assert issubclass(ArxivPapers, OVOSSkill)


@pytest.mark.parametrize("hint", ["arxiv", "the arxiv", "archive", "ArXiv"])
def test_matches_known_aliases(skill, hint):
    assert skill._matches_collection_hint(hint) is True


@pytest.mark.parametrize("hint", ["grimm", "andersen", "the ovos blog"])
def test_does_not_match_other_collections(skill, hint):
    assert skill._matches_collection_hint(hint) is False


def test_none_hint_matches_everyone(skill):
    assert skill._matches_collection_hint(None) is True


@pytest.mark.parametrize("content_type", ["paper", "abstract", "research", "study", "PAPER"])
def test_matches_known_content_types(skill, content_type):
    assert skill._matches_content_type(content_type) is True


@pytest.mark.parametrize("content_type", ["story", "article", "poem"])
def test_does_not_match_other_content_types(skill, content_type):
    assert skill._matches_content_type(content_type) is False


def test_none_content_type_matches_everyone(skill):
    assert skill._matches_content_type(None) is True
