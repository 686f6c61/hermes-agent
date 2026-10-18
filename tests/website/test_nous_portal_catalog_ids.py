"""Every model id the Portal page tells a user to paste into ``/model`` is one the catalogue serves.

``website/docs/integrations/nous-portal.md`` is hand-maintained, and its ``/model`` examples are
the most-copied lines on the page: a stale slug there is a command that fails outright, and a
stale family table under-sells the subscription. The curated manifest shipped in this repository
(``website/static/api/model-catalog.json``, the same artefact ``hermes_cli/model_catalog.py``
fetches for the picker) is the list the catalogue actually serves, so the ids the page presents
have to be drawn from it.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "website" / "docs" / "integrations" / "nous-portal.md"
MANIFEST = ROOT / "website" / "static" / "api" / "model-catalog.json"

# The "want to use a specific provider model that the Portal doesn't expose" section shows the
# OpenRouter-style fallback for an id OUTSIDE the curated list on purpose: a catalogued id there
# would document the opposite of what the section says.
_OFF_CATALOG_EXAMPLE = "anthropic/claude-opus-4.6"

_FENCED = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)
_MODEL_LINE = re.compile(
    r"^\s*/model\s+([a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9.\-]*)\s*(?:#.*)?$", re.MULTILINE
)


def _catalogued_ids() -> set[str]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {entry["id"] for entry in manifest["providers"]["nous"]["models"]}


def _page_model_ids() -> set[str]:
    page = PAGE.read_text(encoding="utf-8")
    found: set[str] = set()
    for block in _FENCED.findall(page):
        found.update(_MODEL_LINE.findall(block))
    return found


def test_portal_page_model_examples_are_catalogued():
    unlisted = _page_model_ids() - _catalogued_ids() - {_OFF_CATALOG_EXAMPLE}
    assert not unlisted, (
        "website/docs/integrations/nous-portal.md offers /model examples the curated catalogue "
        f"({MANIFEST.relative_to(ROOT)}) does not serve: {sorted(unlisted)}"
    )
