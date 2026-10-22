"""Row-wrapping helpers for the classic CLI's prompt_toolkit panels (moved from ``cli_tui_mixin``)."""


def _wrap_rows(wrap, items, width, indent) -> list[tuple[int, str]]:
    """``(index, wrapped_line)`` pairs so selected styling can be re-applied per row."""
    return [(i, w) for i, label in enumerate(items) for w in wrap(label, width, subsequent_indent=indent)]


def _prefix_wrapped_rows(wrap, label, width, first_prefix, indent) -> list[str]:
    """Wrap ``label``, then prefix the rows with ``first_prefix`` / ``indent``.

    The prefix is applied *after* wrapping on purpose. Folding it into the
    string handed to the wrapper charges those columns against the label's own
    width budget — so a selected row wraps one line early and strands the ``❯``
    cursor on a row of its own — and whitespace-trimming wrappers drop the
    leading indent entirely, leaving long unselected labels flush against the
    panel border, out of alignment with every other row.
    """
    rows = wrap(label, width)
    return [(first_prefix if i == 0 else indent) + row for i, row in enumerate(rows)]


def _scroll_list_visible_rows(
    wrap,
    selected: int,
    scroll_offset: int,
    labels: list[str],
    label_width: int,
    indent: str,
    term_rows: int,
    *,
    reserved_below: int = 6,
    panel_chrome: int = 6,
    min_visible: int = 3,
) -> list[tuple[int, list[str]]]:
    """``(label index, wrapped rows)`` for the window of a scrolling panel that fits the screen.

    The window is budgeted in *rows*, not labels: a label takes as many panel rows as its text
    needs, so a label count that matches the terminal height still draws past the bottom of the
    list — the Ctrl+P palette's trailing entries ended up under the composer (#143140).
    ``reserved_below`` matches the approval/clarify panels (input, status bar, separators) and
    ``panel_chrome`` is borders + blanks + the hint row, both charged before the body.

    The returned window is a contiguous, in-order slice that always holds ``selected`` whole;
    ``scroll_offset`` is honoured while it keeps the selection visible, and the slice is filled
    upwards when the selection sits at the tail so the panel does not shrink to one entry.
    """
    rows_by_label = [
        _prefix_wrapped_rows(wrap, label, label_width, "❯ " if idx == selected else "  ", indent)
        for idx, label in enumerate(labels)
    ]
    if not rows_by_label:
        return []
    heights = [len(rows) for rows in rows_by_label]
    last = len(rows_by_label) - 1
    budget = max(min_visible, term_rows - reserved_below - panel_chrome)
    selected = min(max(0, selected), last)

    def _forward(start: int) -> tuple[int, int, int]:
        """``(start, count, used)``: the longest slice from ``start`` inside the budget —
        always at least one label, so an entry taller than the budget still renders."""
        used = count = 0
        idx = start
        while idx <= last and (used == 0 or used + heights[idx] <= budget):
            used += heights[idx]
            count += 1
            idx += 1
        return start, count, used

    start, count, used = _forward(min(max(0, scroll_offset), last))
    if not start <= selected < start + count:
        start, count, used = _forward(selected)
    while start > 0 and used + heights[start - 1] <= budget:
        start -= 1
        count += 1
        used += heights[start]
    return [(idx, rows_by_label[idx]) for idx in range(start, start + count)]

