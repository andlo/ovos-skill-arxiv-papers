"""Shared pytest fixtures for the arxiv skill test suite."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INIT_PATH = Path(__file__).resolve().parents[1] / "__init__.py"
_spec = importlib.util.spec_from_file_location("arxiv_skill", _INIT_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

ArxivPapers = _module.ArxivPapers
FeedFetchError = _module.FeedFetchError
COMMON_READING_SEARCH_RESPONSE = _module.COMMON_READING_SEARCH_RESPONSE
COMMON_READING_FETCH_CONTENT_RESPONSE = _module.COMMON_READING_FETCH_CONTENT_RESPONSE
COMMON_READING_PONG = _module.COMMON_READING_PONG


class FakeFileSystem:
    def __init__(self, base):
        self.base = base
        self.path = str(base)

    def exists(self, name):
        return (self.base / name).exists()

    def open(self, name, mode="r"):
        return open(self.base / name, mode)


@pytest.fixture
def skill(tmp_path, monkeypatch):
    s = ArxivPapers.__new__(ArxivPapers)
    s.log = MagicMock()
    s.skill_id = "ovos-skill-arxiv.test"
    s.status = MagicMock()
    s._bus = MagicMock()
    s._settings = {}
    monkeypatch.setattr(ArxivPapers, "lang", "en-us", raising=False)
    s.file_system = FakeFileSystem(tmp_path)
    s.res_dir = str(Path(__file__).resolve().parents[1])  # repo root, holds locale/
    s._lang_resources = {}  # OVOSSkill.resources' internal per-language cache
    s.category = "cs.AI"
    s.index = {}
    s._translator = None
    s._translator_failed = False
    s._translated_titles_cache = {}
    # matches locale/en-us/collection.voc - most tests don't exercise
    # _load_collection_aliases() itself, they just need this
    # pre-populated the way initialize() would leave it
    s._collection_aliases = ["arxiv", "the arxiv", "archive", "the archive"]
    return s
