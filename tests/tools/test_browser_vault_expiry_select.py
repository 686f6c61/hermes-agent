"""Combined expiry ``<select>``: a four-digit-year option has to be selectable.

The vault derives ``cc-exp`` as ``MM/YY`` from ``exp_month`` + ``exp_year``
(``agent/vault_login_classifier.py::select_checkout_fills``), but hosted
payment pages commonly spell the year with four digits — option values such as
``10/2027`` and visible text such as ``10 / 2027``. The ``<select>`` branch of
the fill script compared the option string against ``MM/YY`` only, so nothing
was selected and the field counted as unfilled.

These cases execute the generated script in node against a stub DOM: the
assertion is what the browser does (``el.value`` after the fill), not the text
of the template.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.vault_login_classifier import build_fill_js

_ORIGIN = "https://gateway.ixopay.com"

_HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");

const change = [];
const el = {
  tagName: "SELECT",
  options: JSON.parse(process.argv[3]),
  value: process.argv[4],
  dispatchEvent: (ev) => { change.push(ev.type); return true; },
  removeAttribute: () => {},
};

global.window = { location: { origin: process.argv[5] } };
global.document = {
  querySelector: (sel) => (sel.indexOf("data-hermes-vault-slot=") !== -1 ? el : null),
  querySelectorAll: () => [],
};

const result = eval(src);
process.stdout.write(JSON.stringify({ result: JSON.parse(result), value: el.value, events: change }));
"""


def _fill_expiry_select(tmp_path: Path, options: list[dict], current: str, secret: str = "10/27") -> dict:
    """Fill one combined-expiry select and report what the page ended up with."""
    node = shutil.which("node") or pytest.skip("node is required to execute the fill script")
    js = build_fill_js([{"index": 3, "token": "cc-exp", "value": secret}], expected_origin=_ORIGIN)
    (tmp_path / "fill.js").write_text(js, encoding="utf-8")
    (tmp_path / "harness.js").write_text(_HARNESS, encoding="utf-8")
    proc = subprocess.run(
        [node, str(tmp_path / "harness.js"), str(tmp_path / "fill.js"), json.dumps(options), current, _ORIGIN],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_four_digit_year_option_value_is_selected(tmp_path):
    options = [{"value": "10/2026", "textContent": "10 / 2026"},
               {"value": "10/2027", "textContent": "10 / 2027"},
               {"value": "11/2027", "textContent": "11 / 2027"}]
    out = _fill_expiry_select(tmp_path, options, current="")
    assert out["result"]["filled"] == 1
    assert out["value"] == "10/2027"
    assert out["events"] == ["change"]


def test_four_digit_year_visible_text_is_matched(tmp_path):
    options = [{"value": "2027-11", "textContent": "11 / 2027"},
               {"value": "2027-10", "textContent": " 10 / 2027 "}]
    out = _fill_expiry_select(tmp_path, options, current="")
    assert out["value"] == "2027-10"


def test_single_digit_month_matches_padded_value(tmp_path):
    options = [{"value": "7/2027", "textContent": "7 / 2027"}]
    out = _fill_expiry_select(tmp_path, options, current="", secret="07/27")
    assert out["value"] == "7/2027"


def test_padded_four_digit_option_matches_padded_value(tmp_path):
    options = [{"value": "01/2027", "textContent": "01 / 2027"}]
    out = _fill_expiry_select(tmp_path, options, current="", secret="01/27")
    assert out["value"] == "01/2027"


def test_two_digit_year_option_still_matches(tmp_path):
    options = [{"value": "10/27", "textContent": "10 / 27"}]
    out = _fill_expiry_select(tmp_path, options, current="")
    assert out["value"] == "10/27"


def test_other_select_tokens_keep_exact_matching(tmp_path):
    # A country select is not an expiry form: "US" must not start matching by whitespace or year.
    options = [{"value": "USA", "textContent": "United States"},
               {"value": "US", "textContent": "US"}]
    out = _fill_expiry_select(tmp_path, options, current="", secret="US")
    assert out["value"] == "US"
    assert out["result"]["filled"] == 1


def test_unmatched_expiry_leaves_the_select_untouched(tmp_path):
    options = [{"value": "12/2028", "textContent": "12 / 2028"}]
    out = _fill_expiry_select(tmp_path, options, current="choose")
    assert out["result"]["filled"] == 0
    assert out["value"] == "choose"
    assert out["events"] == []
