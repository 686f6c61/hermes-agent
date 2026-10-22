"""Row budget for ``CLITuiMixin._render_scroll_list_panel`` (the ``/model`` picker and the Ctrl+P
command palette).

The panel is one child of the root ``HSplit`` above the composer, and the viewport helper budgeted
*labels*: with long entries (``/cmd  —  description``) each label wraps into two or three panel
rows, so a twelve-label window drew thirty rows on a 24-row terminal and pushed the composer over
the bottom of the list — the palette's last command was never visible (#143140).
"""
import hermes_cli.cli_tui_mixin as tui
from cli import _panel_box_width
from hermes_cli.cli_tui_mixin import CLITuiMixin

TERM_ROWS = 24
# ``_render_scroll_list_panel`` reserves ``reserved_below`` (input + status bar + separators) and
# charges the panel chrome (two borders, two blanks, the hint row) inside the budget.
RESERVED_BELOW = 6
CHROME = 6
PALETTE_HINT = "Type to filter 24 commands — ↑/↓ then Enter inserts, Esc cancels"
PALETTE_TITLE = "⚙ Command Palette"


class _Host(CLITuiMixin):
    """Minimal host: the renderer only touches ``state`` + module helpers."""


class _FakeApp:
    """prompt_toolkit hands a dummy app outside a real run; pin its screen size instead."""

    class _Output:
        def __init__(self, rows):
            self._rows = rows

        def get_size(self):
            from prompt_toolkit.data_structures import Size
            return Size(rows=self._rows, columns=80)

    def __init__(self, rows):
        self.output = self._Output(rows)


def _pin_terminal(monkeypatch, rows=TERM_ROWS):
    monkeypatch.setattr("prompt_toolkit.application.get_app", lambda: _FakeApp(rows))


def _panel_text(labels, selected, *, indent="    ", min_width=50, max_width=90,
                title=PALETTE_TITLE, hint=PALETTE_HINT):
    host = _Host()
    frags = host._render_scroll_list_panel(
        {"selected": selected}, title, hint, labels, min_width=min_width, max_width=max_width,
        indent=indent)
    return "".join(t for _style, t in frags)


def _panel_rows(text):
    return [line for line in text.split("\n") if line.startswith("│") or line.startswith("╭")
            or line.startswith("╰")]


def _long_labels(n):
    return [f"/command-{i:02d}  —  " + "a description of what this command does " * 3 + f"({i})"
            for i in range(n)]


def test_palette_fits_the_terminal_body_with_wrapping_labels(monkeypatch):
    _pin_terminal(monkeypatch)
    labels = _long_labels(24)

    for selected in (0, 11, 23):
        rows = _panel_rows(_panel_text(labels, selected))
        assert len(rows) + RESERVED_BELOW <= TERM_ROWS, (
            f"selected={selected}: {len(rows)} panel rows + {RESERVED_BELOW} reserved "
            f"exceeds {TERM_ROWS} terminal rows"
        )


def test_the_last_entry_is_visible_and_selected(monkeypatch):
    _pin_terminal(monkeypatch)
    labels = _long_labels(24)

    text = _panel_text(labels, 23)
    assert "/command-23" in text, "the selected tail entry is drawn"
    assert "❯ /command-23" in text, "and carries the cursor cell"


def test_a_tall_entry_stays_whole_and_keeps_the_cursor_row(monkeypatch):
    _pin_terminal(monkeypatch)
    labels = ["/very-long-command-name  —  " + "x" * 200, "/help  —  Help"]

    text = _panel_text(labels, 0)
    rows = _panel_rows(text)
    assert len(rows) + RESERVED_BELOW <= TERM_ROWS, rows
    assert "❯ /very-long-command-name" in text
    # The continuation rows carry the palette's own indent, never the cursor cell.
    assert "    xxx" in text
    assert "❯ xxx" not in text


def test_short_lists_render_every_label(monkeypatch):
    _pin_terminal(monkeypatch, 60)
    labels = ["/model  —  Switch the active model", "/help  —  Help"]

    rows = _panel_rows(_panel_text(labels, 0))
    assert "│ ❯ /model  —  Switch the active model" in "\n".join(rows)
    assert "│   /help  —  Help" in "\n".join(rows)


def test_body_rows_never_exceed_the_label_count_of_the_slice():
    """The slice is still a contiguous window over the labels, in order."""
    from hermes_cli.cli_tui_wrap import _scroll_list_visible_rows
    from cli import _wrap_panel_text

    labels = _long_labels(24)
    body = _panel_box_width(PALETTE_TITLE, [PALETTE_HINT] + labels, min_width=50, max_width=90) - 2
    window = _scroll_list_visible_rows(
        _wrap_panel_text, 23, 0, labels, max(8, body - 4), "    ", TERM_ROWS)

    indices = [idx for idx, _rows in window]
    assert indices == list(range(indices[0], indices[-1] + 1)), indices
    assert indices[-1] == 23
    assert sum(len(rows) for _idx, rows in window) <= TERM_ROWS - RESERVED_BELOW - CHROME


def _plain_wrap(text, width):
    """One row per label: exercises the window math without wrapping noise."""
    return [text]


class TestScrollListViewport:
    """The label-level invariants the picker relied on, now measured on the row window."""

    def _window(self, selected, offset, n=36, term_rows=30):
        from hermes_cli.cli_tui_wrap import _scroll_list_visible_rows
        labels = [f"/entry-{i:02d}" for i in range(n)]
        rows = _scroll_list_visible_rows(_plain_wrap, selected, offset, labels, 40, "  ", term_rows)
        return rows

    def test_short_list_needs_no_scroll(self):
        rows = self._window(0, 0, n=5, term_rows=30)
        assert [idx for idx, _r in rows] == [0, 1, 2, 3, 4]

    def test_offset_recovers_after_a_stage_switch(self):
        rows = self._window(0, 25)
        assert next(idx for idx, _r in rows) == 0, (
            "a stale offset must collapse when the cursor is back at the top"
        )

    def test_navigation_keeps_the_cursor_in_the_window(self):
        offset = 0
        for cursor in list(range(36)) + list(range(35, -1, -1)):
            window = self._window(cursor, offset)
            indices = [idx for idx, _r in window]
            assert cursor in indices, f"cursor={cursor} out of window {indices}"
            offset = indices[0]
