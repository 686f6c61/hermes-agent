"""A failed pytest-ancestor walk must not stick (#126766).

``_has_pytest_ancestor`` fails open when psutil cannot walk the process tree.
Memoizing that ``False`` disarms the production state.db guard for the rest of
the process, even after a later walk would see pytest.
"""

import hermes_state_guard as guard


class _Proc:
    def __init__(self, argv):
        self._argv = list(argv)

    def cmdline(self):
        return list(self._argv)


class _Psutil:
    def __init__(self, walks):
        self.walks = list(walks)

    def Process(self):
        return self

    def parents(self):
        item = self.walks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return [_Proc(argv) for argv in item]


def test_transient_ancestor_walk_error_is_not_memoized(monkeypatch):
    """A PermissionError on the first walk must not cache ``False``."""
    fake = _Psutil([
        PermissionError("transient"),
        [["/usr/bin/pytest", "tests/test_x.py"]],
    ])
    monkeypatch.setattr(guard, "psutil", fake)
    monkeypatch.setattr(guard, "_PYTEST_ANCESTOR", None)

    assert guard._has_pytest_ancestor() is False
    assert guard._PYTEST_ANCESTOR is None
    assert guard._has_pytest_ancestor() is True
    assert guard._PYTEST_ANCESTOR is True


def test_successful_ancestor_walk_stays_memoized(monkeypatch):
    """A completed walk is still cached: the tree above us does not change."""
    fake = _Psutil([[["/usr/bin/python3"]]])
    monkeypatch.setattr(guard, "psutil", fake)
    monkeypatch.setattr(guard, "_PYTEST_ANCESTOR", None)

    assert guard._has_pytest_ancestor() is False
    assert guard._has_pytest_ancestor() is False
    assert fake.walks == []
    assert guard._PYTEST_ANCESTOR is False
