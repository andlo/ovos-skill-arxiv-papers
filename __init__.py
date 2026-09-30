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
from ovos_bus_client.session import SessionManager
from ovos_bus_client.message import Message
from pathlib import Path
from ovos_utils.parse import match_one
from ovos_utils import classproperty
from ovos_utils.process_utils import RuntimeRequirements

import requests
import xml.etree.ElementTree as ET
import re
import time
import json


def _user_agent():
    """Say who is asking. Some sites answer python-requests' default
    User-Agent with 403 (365tomorrows.com behind Cloudflare does), and a
    descriptive one is what sites ask automated clients to send."""
    try:
        from importlib.metadata import version
        ver = version("ovos-skill-arxiv-papers")
    except Exception:
        ver = "unknown"
    return f"ovos-skill-arxiv-papers/{ver} (+https://github.com/andlo/ovos-skill-arxiv-papers)"


HTTP_HEADERS = {"User-Agent": _user_agent()}

FEED_URL_TEMPLATE = "https://rss.arxiv.org/rss/{category}"
DEFAULT_CATEGORY = "cs.AI"
DC_CREATOR_TAG = "{http://purl.org/dc/elements/1.1/}creator"
ABSTRACT_RE = re.compile(r"Abstract:\s*(.+)", re.DOTALL)


def _read_voc(path):
    """Phrases in a .voc file: one per line, "a|b" and "(a|b) c" expanded
    the simple way ovos-workshop does for single groups."""
    phrases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.*)\(([^)]*)\)(.*)$", line)
        if m:
            phrases += [" ".join(f"{m.group(1)}{alt}{m.group(3)}".split()) for alt in m.group(2).split("|")]
        else:
            phrases += [alt.strip() for alt in line.split("|") if alt.strip()]
    return phrases


class FeedFetchError(Exception):
    """Raised when the arXiv feed could not be fetched or parsed."""


COMMON_READING_SEARCH = "ovos.common_reading.search"
COMMON_READING_SEARCH_RESPONSE = "ovos.common_reading.search.response"
COMMON_READING_FETCH_CONTENT = "ovos.common_reading.fetch_content"  # + ".{this_skill_id}"
COMMON_READING_FETCH_CONTENT_RESPONSE = "ovos.common_reading.fetch_content.response"
COMMON_READING_PING = "ovos.common_reading.ping"
COMMON_READING_PONG = "ovos.common_reading.pong"
# vocabulary: the words people use for what this provider can read, one
# message per language it serves - announced when it loads and whenever
# the pipeline asks (see the pipeline plugin's README, "4. Vocabulary").
# Without it the pipeline (0.3.0+) never sends a request here.
COMMON_READING_VOCABULARY = "ovos.common_reading.vocabulary"
COMMON_READING_VOCABULARY_GET = "ovos.common_reading.vocabulary.get"

# this provider translates and works on ANY device language (unlike
# andersen-tales/grimm-tales's fixed SUPPORTED_LANGUAGES set) - so
# collection_hint aliases are loaded per-language from
# locale/<lang>/collection.voc where we've bothered to translate them
# (the pipeline's own 8 supported languages), falling back to this
# English list for anything else. COLLECTION_NAME stays an untranslated
# proper noun ("arXiv") - only the ALIASES need localizing. See
# ovos-common-reading-pipeline-plugin#26.
FALLBACK_COLLECTION_ALIASES = ["arxiv", "the arxiv", "archive", "the archive"]
CONTENT_TYPES = ["paper", "abstract", "research", "study"]
COLLECTION_HINT_THRESHOLD = 0.85
COLLECTION_NAME = "arXiv"
SOURCE_NAME = "arxiv.org"



def primary_subtag(lang):
    """'en-US', 'en_gb', 'EN' -> 'en'."""
    return (lang or "").replace("_", "-").split("-")[0].lower()


def configured_languages(langs):
    """Primary subtags of the languages an installation is configured
    for (core lang + secondary_langs): ['en-US', 'da-DK'] -> {'en', 'da'}."""
    return {primary_subtag(lang) for lang in langs or [] if lang}

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
        self._load_collection_aliases()
        self.refresh_index()
        self.add_event(COMMON_READING_SEARCH, self.handle_search)
        self.add_event(f"{COMMON_READING_FETCH_CONTENT}.{self.skill_id}", self.handle_fetch_content)
        self.add_event(COMMON_READING_PING, self.handle_ping)
        self.add_event(COMMON_READING_VOCABULARY_GET, self.handle_vocabulary_get)
        self._announce_vocabulary()

    def _load_collection_aliases(self):
        """Loads collection_hint aliases for the CURRENT device language
        via OVOS's own resource file resolution (self.resources), falling
        back to FALLBACK_COLLECTION_ALIASES (English) if this language
        hasn't been translated. See ovos-common-reading-pipeline-plugin#26."""
        aliases_raw = self.resources.load_vocabulary_file("collection")
        aliases = [phrase for line in aliases_raw for phrase in line]
        self._collection_aliases = aliases or FALLBACK_COLLECTION_ALIASES

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
            r = requests.get(url, timeout=10, headers=HTTP_HEADERS)
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
        _, score = match_one(hint.lower(), self._collection_aliases)
        return score >= COLLECTION_HINT_THRESHOLD

    def _matches_content_type(self, content_type):
        if not content_type:
            return True
        return content_type.lower() in CONTENT_TYPES


    @staticmethod
    def _request_lang(message):
        """The language a request was made in, or None when it does not
        say: the pipeline plugin's own 'lang' field first, then the
        language of the session the request was forwarded from (a
        HiveMind client's, on a hub). An older plugin sends neither."""
        lang = message.data.get("lang") or message.context.get("lang")
        if not lang and message.context.get("session"):
            lang = SessionManager.get(message).lang
        return lang or None

    def _serves(self, lang):
        """This provider translates, so it could answer in any language -
        but it only does for the languages this installation is
        configured for (the device's lang plus secondary_langs in
        mycroft.conf). A request in any other language would otherwise
        load a translation model and translate the whole catalogue of
        titles for a language nobody here speaks."""
        return primary_subtag(lang) in configured_languages(self.native_langs)

    def handle_search(self, message):
        if not self._serves(self._request_lang(message) or self.lang):
            return  # not a language this installation is configured for
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

    def _vocabulary_langs(self):
        return sorted(configured_languages(self.native_langs))

    def _locale_words(self, name, lang):
        """The phrases of locale/<lang>/<name>.voc for a primary language
        tag ("da"), or [] when this skill has no such file for it."""
        base = Path(__file__).resolve().parent / "locale"
        for folder in sorted(base.iterdir()) if base.is_dir() else []:
            if folder.name.split("-")[0] == lang and (folder / f"{name}.voc").is_file():
                return _read_voc(folder / f"{name}.voc")
        return []

    def _vocabulary(self, lang):
        """The kind of text this provider serves (locale/<lang>/content_type.voc,
        announced under its canonical name CONTENT_TYPES[0]) and its
        collection names (collection.voc) in `lang`. No titles: they change
        daily and are only known in the source's own language."""
        words = self._locale_words("content_type", lang)
        return {"content_types": {CONTENT_TYPES[0]: words} if words else {},
                "collections": self._locale_words("collection", lang) or list(FALLBACK_COLLECTION_ALIASES)}

    def _announce_vocabulary(self, langs=None, message=None):
        """One ovos.common_reading.vocabulary per language served (and
        asked for, when the pipeline named languages)."""
        wanted = {str(l).lower().split("-")[0].split("_")[0] for l in (langs or [])}
        for lang in self._vocabulary_langs():
            if wanted and lang not in wanted:
                continue
            data = {"skill_id": self.skill_id, "lang": lang, **self._vocabulary(lang)}
            msg = message.reply(COMMON_READING_VOCABULARY, data) if message else \
                Message(COMMON_READING_VOCABULARY, data)
            self.bus.emit(msg)

    def handle_vocabulary_get(self, message):
        self._announce_vocabulary(message.data.get("langs"), message)

    def shutdown(self):
        """The pipeline stops sending requests meant for this provider."""
        try:
            self.bus.emit(Message(COMMON_READING_VOCABULARY, {"skill_id": self.skill_id, "remove": True}))
        except Exception:
            pass
        super().shutdown()

    def handle_ping(self, message):
        """Cheap 'is anyone there?' reply - no index lookup, no
        translation. Only ever called by the pipeline plugin on its
        rare 0-candidates path (see
        ovos-common-reading-pipeline-plugin#2), never on every search."""
        lang = self._request_lang(message)
        if lang and not self._serves(lang):
            return
        self.bus.emit(message.reply(COMMON_READING_PONG, {
            "skill_id": self.skill_id,
            "collection": COLLECTION_NAME,
        }))
