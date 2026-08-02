"""#76628: reject pure-splat search_files patterns that force full-tree walks."""

from tools.file_tools import _is_unscoped_search_pattern, search_tool


def test_files_target_pure_star_is_unscoped():
    assert _is_unscoped_search_pattern("*", "files") is True
    assert _is_unscoped_search_pattern("**", "files") is True
    assert _is_unscoped_search_pattern("*.py", "files") is False
    assert _is_unscoped_search_pattern("*config*", "files") is False


def test_content_target_match_all_regex_is_unscoped():
    assert _is_unscoped_search_pattern(".*", "content") is True
    assert _is_unscoped_search_pattern(".+", "content") is True
    assert _is_unscoped_search_pattern("def ", "content") is False
    assert _is_unscoped_search_pattern("foo.*bar", "content") is False


def test_search_tool_blocks_pure_star_files(tmp_path, monkeypatch):
    # Avoid needing a real file backend; the guard fires before ops.
    result = search_tool(pattern="*", target="files", path=str(tmp_path))
    assert "BLOCKED" in result
    assert "unscoped wildcard" in result


def test_search_tool_allows_narrow_glob(tmp_path):
    # Create one file so a non-blocked path can succeed or fail cleanly.
    (tmp_path / "app.py").write_text("x\n", encoding="utf-8")
    result = search_tool(pattern="*.py", target="files", path=str(tmp_path))
    assert "BLOCKED" not in result
