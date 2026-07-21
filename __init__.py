"""
skill OVOS arXiv Papers
Copyright (C) 2026  Andreas Lorensen

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

---

Provider skill for ovos-common-reading-pipeline-plugin: reads arXiv
paper abstracts aloud (content_type: "paper"/"abstract"/"research") - a
second real-world test that common-reading works for more than fairy
tales, and that a new content_type is easy for a provider to introduce.

Only the ABSTRACT is read, not the full paper - papers themselves are
PDFs, out of scope for TTS narration; abstracts are the right size for
"read me a recent AI paper".

Registers no intents of its own; see
https://github.com/andlo/ovos-common-reading-pipeline-plugin for the
full protocol. Needs the pipeline plugin installed and configured to be
useful - has no standalone voice interface.

Like ovos-skill-ovosblog, this machine-translates for non-English
devices (with disclosure, and declining to respond at all if no
translation plugin is available) using whatever ovos-plugin-manager
language-translation plugin is configured.
"""

from ovos_workshop.skills import OVOSSkill
from ovos_utils.parse import match_one
from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements

import requests
import xml.etree.ElementTree as ET
import re
import time
import json

FEED_URL_TEMPLATE = "https://rss.arxiv.org/rss/{category}"
DEFAULT_CATEGORY = "cs.AI"
DC_CREATOR_TAG = "{http://purl.org/dc/elements/1.1/}creator"
ABSTRACT_RE = re.compile(r"Abstract:\s*(.+)", re.DOTALL)


class FeedFetchError(Exception):
    """Raised when the arXiv feed could not be fetched or parsed."""


COMMON_READING_SEARCH = "ovos.common_reading.search"
COMMON_READING_SEARCH_RESPONSE = "ovos.common_reading.search.response"
COMMON_READING_FETCH_CONTENT = "ovos.common_reading.fetch_content"  # + ".{this_skill_id}"
COMMON_READING_FETCH_CONTENT_RESPONSE = "ovos.common_reading.fetch_content.response"

COLLECTION_ALIASES = ["arxiv", "the arxiv", "archive", "the archive"]
CONTENT_TYPES = ["paper", "abstract", "research", "study"]
COLLECTION_HINT_THRESHOLD = 0.85
COLLECTION_NAME = "arXiv"
SOURCE_NAME = "arxiv.org"


class ArxivPapers(OVOSSkill):

    INDEX_CACHE_TTL = 60 * 60 * 24  # 24h - matches arXiv's own daily feed rebuild schedule

    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(
            internet_before_load=True,
            network_before_load=True,
            requires_internet=True,
            requires_network=True,
            no_internet_fallback=True,
            no_network_fallback=True,
        )

    def initialize(self):
        self.category = self.settings.get('category', DEFAULT_CATEGORY)
        self.index = {}  # link -> {title, author, abstract, pubdate}
        self._translator = None
        self._translator_failed = False
        self._translated_titles_cache = {}
        self.refresh_index()
        self.add_event(COMMON_READING_SEARCH, self.handle_search)
        self.add_event(f"{COMMON_READING_FETCH_CONTENT}.{self.skill_id}", self.handle_fetch_content)

    def _index_cache_filename(self):
        return f"feed_index_{self.category}.json"

    def _read_index_cache(self):
        cache_file = self._index_cache_filename()
        if not self.file_system.exists(cache_file):
            return None
        try:
            with self.file_system.open(cache_file, "r") as f:
                return json.load(f)
        except (OSError, ValueError) as e:
            self.log.warning(f"could not read index cache: {e}")
            return None

    def _write_index_cache(self):
        cache_file = self._index_cache_filename()
        try:
            with self.file_system.open(cache_file, "w") as f:
                json.dump({"timestamp": time.time(), "index": self.index}, f)
        except OSError as e:
            self.log.warning(f"could not write index cache: {e}")

    def refresh_index(self, force=False):
        cached = self._read_index_cache()
        if not force and cached and (time.time() - cached.get("timestamp", 0)) < self.INDEX_CACHE_TTL:
            self.index = cached.get("index", {})
            self._translated_titles_cache.clear()
            return
        try:
            self.index = self.fetch_feed_index()
            self._write_index_cache()
            self._translated_titles_cache.clear()
        except FeedFetchError as e:
            self.log.error(f"Could not refresh arXiv feed index: {e}")
            if cached:
                self.log.warning("Falling back to previously cached (possibly stale) feed index")
                self.index = cached.get("index", {})
                self._translated_titles_cache.clear()

    def fetch_feed_index(self):
        url = FEED_URL_TEMPLATE.format(category=self.category)
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            raise FeedFetchError(f"failed to fetch {url}: {e}") from e
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError as e:
            raise FeedFetchError(f"failed to parse feed XML: {e}") from e

        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else []
        index = {}
        for item in items:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            raw_description = item.findtext("description") or ""
            match = ABSTRACT_RE.search(raw_description)
            abstract = match.group(1).strip() if match else raw_description.strip()
            index[link] = {
                "title": title,
                "author": (item.findtext(DC_CREATOR_TAG) or "").strip(),
                "abstract": abstract,
                "pubdate": (item.findtext("pubDate") or "").strip(),
            }
        if not index:
            raise FeedFetchError("feed parsed but contained no usable items")
        return index

    def _latest_link(self):
        from email.utils import parsedate_to_datetime
        best_link, best_date = None, None
        for link, entry in self.index.items():
            try:
                d = parsedate_to_datetime(entry["pubdate"])
            except (TypeError, ValueError):
                continue
            if best_date is None or d > best_date:
                best_date, best_link = d, link
        return best_link or (next(iter(self.index), None))

    def _get_translator(self):
        if self._translator is None and not self._translator_failed:
            try:
                from ovos_plugin_manager.language import OVOSLangTranslationFactory
                self._translator = OVOSLangTranslationFactory.create()
            except Exception as e:
                self.log.warning(f"no language translation plugin available: {e}")
                self._translator_failed = True
        return self._translator

    def _get_translated_titles(self, lang):
        """Match against *translated* titles, not English ones. Returns
        None if translation isn't possible - callers must treat that as
        'we cannot offer anything in this language' rather than falling
        back to English titles (see ovos-skill-ovosblog for the reasoning
        behind this, found via user feedback on the same design there)."""
        target = lang.split("-")[0]
        if target == "en":
            return {link: entry["title"] for link, entry in self.index.items()}

        cached = self._translated_titles_cache.get(target)
        if cached is not None:
            return cached

        translator = self._get_translator()
        if translator is None:
            return None

        translated = {}
        try:
            for link, entry in self.index.items():
                translated[link] = translator.translate(entry["title"], target=target, source="en")
        except Exception as e:
            self.log.warning(f"failed to translate titles to '{target}': {e}")
            return None

        self._translated_titles_cache[target] = translated
        return translated

    def _maybe_translate_paragraphs(self, paragraphs, lang):
        target = lang.split("-")[0]
        if target == "en":
            return paragraphs, False
        translator = self._get_translator()
        if translator is None:
            return paragraphs, False
        try:
            translated = [translator.translate(p, target=target, source="en") for p in paragraphs]
            return translated, True
        except Exception as e:
            self.log.warning(f"translation failed, falling back to English: {e}")
            return paragraphs, False

    def _matches_collection_hint(self, hint):
        if not hint:
            return True
        _, score = match_one(hint.lower(), COLLECTION_ALIASES)
        return score >= COLLECTION_HINT_THRESHOLD

    def _matches_content_type(self, content_type):
        if not content_type:
            return True
        return content_type.lower() in CONTENT_TYPES

    def handle_search(self, message):
        if not self.index:
            return
        collection_hint = message.data.get("collection_hint")
        if not self._matches_collection_hint(collection_hint):
            return
        content_type = message.data.get("content_type")
        if not self._matches_content_type(content_type):
            return

        titles = self._get_translated_titles(self.lang)
        if titles is None:
            return  # can't offer this language without a translator

        phrase = message.data.get("phrase")
        if phrase:
            title, confidence = match_one(phrase, list(titles.values()))
            link = next(l for l, t in titles.items() if t == title)
        elif collection_hint:
            # 'read me something from arXiv' with no specific title - the
            # most recent paper in the configured category
            link = self._latest_link()
            title = titles[link]
            confidence = 1.0
        else:
            return

        self.bus.emit(message.reply(COMMON_READING_SEARCH_RESPONSE, {
            "skill_id": self.skill_id,
            "content_id": link,
            "title": title,
            "author": self.index[link].get("author") or "",
            "collection": f"{COLLECTION_NAME} ({self.category})",
            "source": SOURCE_NAME,
            "confidence": confidence,
            "machine_translated": self.lang.split("-")[0] != "en",
        }))

    def handle_fetch_content(self, message):
        content_id = message.data.get("content_id")
        entry = self.index.get(content_id)
        if not entry:
            self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": []}))
            return
        paragraphs, _ = self._maybe_translate_paragraphs([entry["abstract"]], self.lang)
        self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE, {"paragraphs": paragraphs}))
