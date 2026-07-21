"""Tests for feed fetching/parsing, including the abstract-extraction
regex (stripping arXiv's 'arXiv:ID vN Announce Type: X\\nAbstract:'
prefix from the raw RSS description)."""
from unittest.mock import MagicMock

import pytest
import requests
from conftest import FeedFetchError

SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:arxiv="http://arxiv.org/schemas/atom" version="2.0"><channel>
<title>cs.AI updates on arXiv.org</title>
<item>
  <title>Older Paper</title>
  <link>https://arxiv.org/abs/2607.00001</link>
  <guid isPermaLink="false">oai:arXiv.org:2607.00001v1</guid>
  <description>arXiv:2607.00001v1 Announce Type: new
Abstract: This is the older abstract text.</description>
  <dc:creator>Alice Smith</dc:creator>
  <pubDate>Mon, 01 Jan 2024 00:00:00 -0400</pubDate>
</item>
<item>
  <title>Newer Paper</title>
  <link>https://arxiv.org/abs/2607.00002</link>
  <guid isPermaLink="false">oai:arXiv.org:2607.00002v1</guid>
  <description>arXiv:2607.00002v1 Announce Type: new
Abstract: This is the newer abstract text.</description>
  <dc:creator>Bob Jones, Carol Lee</dc:creator>
  <pubDate>Wed, 01 Jan 2025 00:00:00 -0400</pubDate>
</item>
</channel></rss>"""


def test_fetch_feed_index_parses_items_and_strips_abstract_prefix(skill, monkeypatch):
    fake_response = MagicMock(content=SAMPLE_FEED.encode("utf-8"))
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)

    index = skill.fetch_feed_index()

    assert len(index) == 2
    entry = index["https://arxiv.org/abs/2607.00001"]
    assert entry["title"] == "Older Paper"
    assert entry["author"] == "Alice Smith"
    assert entry["abstract"] == "This is the older abstract text."


def test_fetch_feed_index_uses_configured_category(skill, monkeypatch):
    requested_urls = []

    def fake_get(url, timeout):
        requested_urls.append(url)
        return MagicMock(content=SAMPLE_FEED.encode("utf-8"), raise_for_status=MagicMock())

    monkeypatch.setattr(requests, "get", fake_get)
    skill.category = "cs.CL"

    skill.fetch_feed_index()

    assert requested_urls == ["https://rss.arxiv.org/rss/cs.CL"]


def test_fetch_feed_index_network_error_raises(skill, monkeypatch):
    def fail(*a, **kw):
        raise requests.ConnectionError("boom")
    monkeypatch.setattr(requests, "get", fail)

    with pytest.raises(FeedFetchError):
        skill.fetch_feed_index()


def test_latest_link_picks_most_recent_pubdate(skill, monkeypatch):
    fake_response = MagicMock(content=SAMPLE_FEED.encode("utf-8"))
    fake_response.raise_for_status = MagicMock()
    monkeypatch.setattr(requests, "get", lambda *a, **kw: fake_response)
    skill.index = skill.fetch_feed_index()

    latest = skill._latest_link()

    assert latest == "https://arxiv.org/abs/2607.00002"
