"""The pdf skill must draw code points a base-14 font cannot encode.

Helvetica's WinAnsi set has no ``ő``/``ű``, so a PDF built from the sample
stylesheet stored them but drew empty boxes. These tests pin the TrueType
registration that fixes it, and the honest warning when no such font exists.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load_create_module():
    spec = importlib.util.spec_from_file_location("pdf_create_under_test", SCRIPTS / "pdf_create.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(script: str, *args: str, expect: int = 0) -> subprocess.CompletedProcess:
    env = dict(os.environ, LC_ALL="C", LANG="C", PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args],
        capture_output=True, text=True, encoding="utf-8", env=env, check=False,
    )
    assert proc.returncode == expect, f"{script} {args}: rc={proc.returncode}\n{proc.stderr}"
    return proc


def test_resolver_reports_a_pair_only_when_a_candidate_exists(tmp_path, monkeypatch):
    module = load_create_module()
    available = any(
        os.path.exists(regular) and os.path.exists(bold)
        for regular, bold in module._UNICODE_FONT_PAIRS
    )
    assert (module._register_unicode_font() is not None) is available

    monkeypatch.setattr(module, "_UNICODE_FONT_PAIRS", ())
    assert module._register_unicode_font() is None


def test_fallback_warns_instead_of_drawing_silent_boxes(monkeypatch, capsys):
    module = load_create_module()
    monkeypatch.setattr(module, "_UNICODE_FONT_PAIRS", ())
    module._warn_on_unencodable_text({"title": "tűz", "elements": []}, None)
    err = capsys.readouterr().err
    assert "no Unicode TrueType font found" in err
    assert "ű" in err

    module._warn_on_unencodable_text({"title": "plain ascii"}, None)
    assert capsys.readouterr().err == ""


def test_hungarian_double_acute_letters_survive_into_the_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    module = load_create_module()
    if module._register_unicode_font() is None:
        pytest.skip("host has no Unicode TrueType font to register")

    spec = {
        "title": "Magyar minta",
        "elements": [
            {"type": "heading", "text": "Időpont egyeztetés", "level": 1},
            {"type": "paragraph", "text": "Kérjük, jöjjön előre, a tűz is ég."},
            {"type": "table", "rows": [["Város", "Időpont"], ["Győr", "előre"]], "header": True},
        ],
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "magyar.pdf"
    run("pdf_create.py", str(spec_path), "-o", str(out))

    doc = pymupdf.open(out)
    page = doc[0]
    text = page.get_text()
    fonts = page.get_fonts()
    doc.close()

    assert "ő" in text and "ű" in text, text
    assert "Időpont" in text and "Győr" in text and "tűz" in text, text
    assert any(font[2] == "TrueType" for font in fonts), fonts
