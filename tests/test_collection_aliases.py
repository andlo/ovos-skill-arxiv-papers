"""Tests for _load_collection_aliases() against the real locale/<lang>/
collection.voc files, and the fallback-to-English behavior for any
device language we haven't bothered translating aliases for (this
provider works on ANY language via translation - see
ovos-common-reading-pipeline-plugin#26)."""
import pytest


@pytest.mark.parametrize("lang", ["en-us", "da-dk", "de-de", "es-es", "fr-fr", "it-it", "nl-nl", "pt-pt"])
def test_load_collection_aliases_per_language(skill, monkeypatch, lang):
    monkeypatch.setattr(type(skill), "lang", lang, raising=False)

    skill._load_collection_aliases()

    assert len(skill._collection_aliases) > 0
    assert all(isinstance(a, str) for a in skill._collection_aliases)


def test_danish_alias_matches_danish_phrasing(skill, monkeypatch):
    monkeypatch.setattr(type(skill), "lang", "da-dk", raising=False)
    skill._load_collection_aliases()

    assert skill._matches_collection_hint("videnskabelige artikler") is True


def test_falls_back_to_english_for_untranslated_language(skill, monkeypatch):
    """Japanese has no locale/ja-jp/collection.voc and no close relative
    to fall back to via langcodes."""
    monkeypatch.setattr(type(skill), "lang", "ja-jp", raising=False)

    skill._load_collection_aliases()

    assert skill._collection_aliases == ["arxiv", "the arxiv", "archive", "the archive"]
