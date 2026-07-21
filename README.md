# <img src='book-512.png' card_color='#40DBB0' width='50' height='50' style='vertical-align:bottom'/> arXiv Papers (provider)

A *provider* skill for [ovos-common-reading-pipeline-plugin](https://github.com/andlo/ovos-common-reading-pipeline-plugin),
reading [arXiv](https://arxiv.org/) paper abstracts aloud.

A second real-world test that common-reading works for more than fairy
tales - this one introduces a new `content_type` ("paper"), sourced from
a completely different kind of feed (per-category, updated daily).

[![Tests](https://github.com/andlo/ovos-skill-arxiv-papers/actions/workflows/test.yml/badge.svg)](https://github.com/andlo/ovos-skill-arxiv-papers/actions/workflows/test.yml)
[![PyPI version](https://img.shields.io/pypi/v/ovos-skill-arxiv-papers.svg)](https://pypi.org/project/ovos-skill-arxiv-papers/)

> **This skill has no standalone voice interface.** It registers no
> intents and never speaks. It only answers
> [ovos.common_reading.* bus messages](https://github.com/andlo/ovos-common-reading-pipeline-plugin#the-ovoscommon_reading-bus-protocol),
> so you also need **ovos-common-reading-pipeline-plugin** installed and
> added to your pipeline config for it to be useful at all.

## Install
```bash
pip install ovos-skill-arxiv-papers ovos-common-reading-pipeline-plugin
```

## Source

Feeds from `https://rss.arxiv.org/rss/<category>` (RSS 2.0), one
subject category at a time - default `cs.AI`, configurable via this
skill's settings (`category`, e.g. `cs.CL`, `math.QA`, `q-bio.NC` - see
[arXiv's category taxonomy](https://arxiv.org/category_taxonomy)).
Refreshed at most once a day, matching arXiv's own daily feed rebuild
schedule.

Only the **abstract** is read, not the full paper - papers are PDFs,
out of scope for TTS narration. The raw feed description includes
arXiv's own `arXiv:<id> Announce Type: <type>` header before the
abstract text; this provider strips that off before offering the text.

## Translation

Like `ovos-skill-ovosblog`, this machine-translates titles (for matching
and search responses) and abstracts (when reading them aloud) for
non-English devices, using whatever
[ovos-plugin-manager](https://github.com/OpenVoiceOS/ovos-plugin-manager)
language-translation plugin is configured. Search responses include
`"machine_translated": true/false` for disclosure.

If no translation plugin is available, this provider does not respond
to searches at all for a non-English device, rather than silently
offering English content the user didn't ask for.

**Note for anyone comparing providers:** unlike
`ovos-skill-andersen-tales`/`ovos-skill-grimm-tales`/
`ovos-skill-andrew-lang-tales`, which check a fixed `SUPPORTED_LANGUAGES`
set at load time and refuse to load at all otherwise, this provider
*always* loads regardless of device language - it can't know in advance
whether a translation plugin will be available, so it always registers
its bus events and decides per-search instead (see above).

## Collection hints

Responds to `collection_hint` values like "arxiv", "the arxiv", and
"archive"/"the archive" (arXiv is commonly pronounced "archive", so
that's a likely STT transcription).

## Content type

Responds to `content_type` hints of "paper", "abstract", "research", or
"study". Ignores everything else (e.g. "story", "article").

## "Surprise me"

A search with no specific `phrase` but a matching `collection_hint`
(e.g. "read me a paper from arXiv") returns the **most recent** paper in
the configured category, by `pubDate`.

## Terms of use

arXiv explicitly provides these per-category RSS feeds for this kind of
use (see [arXiv's RSS documentation](https://info.arxiv.org/help/rss.html)) -
review the [Terms of Use for arXiv APIs](https://info.arxiv.org/help/api/tou.html)
before adjusting the request frequency below the daily cache TTL here.

## Credits

Content and feed from [arxiv.org](https://arxiv.org/), an open-access
e-print repository operated by Cornell University.

## Category
**Science**

## Tags
#science #research #arxiv #papers #provider
