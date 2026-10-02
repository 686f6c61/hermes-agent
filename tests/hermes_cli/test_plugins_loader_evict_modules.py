"""#131817: _evict_modules() must snapshot sys.modules before iterating.

Plugin loads run on concurrent worker threads; a sibling thread's ``import``
inserts into ``sys.modules`` while the evict loop walks it, and every plugin
in the batch dies with ``RuntimeError: dictionary changed size during
iteration``. The snapshot has to be ``dict.copy()``, which is atomic at the
C level: a plain iteration — even inside a list comprehension or
``list(sys.modules)`` — walks the live dict through the iterator protocol and
still races the insert.
"""

import sys
import types

from hermes_cli.plugins_loader import _evict_modules


class _ConcurrentImportModules(dict):
    """``sys.modules`` stand-in that inserts a key mid-iteration, like a sibling
    worker thread's import would during plugin discovery."""

    def __iter__(self):
        source = super().__iter__()

        def _gen():
            for index, name in enumerate(source):
                if index == 0:
                    self["sneaky.concurrent.import"] = types.ModuleType(
                        "sneaky.concurrent.import")
                yield name

        return _gen()


def test_evict_modules_survives_concurrent_insert(monkeypatch):
    """A concurrent insert during iteration must not kill the eviction."""
    racy = _ConcurrentImportModules({
        "basic": types.ModuleType("basic"),
        "basic.helper": types.ModuleType("basic.helper"),
    })
    monkeypatch.setattr(sys, "modules", racy)

    _evict_modules("basic")

    assert "basic" not in racy
    assert "basic.helper" not in racy
    # The atomic snapshot never walks the live dict, so the simulated
    # mid-iteration insert is not observed at all — and crucially, the
    # eviction did not die with "dictionary changed size during iteration".
    assert "sneaky.concurrent.import" not in racy


def test_evict_modules_keeps_unrelated_prefixes():
    modules = {
        "basic": types.ModuleType("basic"),
        "basic.helper": types.ModuleType("basic.helper"),
        "basic_extra": types.ModuleType("basic_extra"),
        "other": types.ModuleType("other"),
    }
    monkey = modules
    original = sys.modules
    sys.modules = monkey
    try:
        _evict_modules("basic")
    finally:
        sys.modules = original

    assert "basic_extra" in modules
    assert "other" in modules
