"""`pm install._identity` must honor its contract for artifacts without a digest.

A lock can pin a package whose artifact is a container reference (for example
`docker://termux/termux-docker@sha256:...` on the Termux target). That artifact
dict carries no `sha256` key of its own, so nothing about it is digest-bound.
`_identity`'s contract (its docstring) is to return `None` when the lock pins
nothing digest-bound, but iterating `a["sha256"]` unconditionally raised
`KeyError` instead — crashing `hermes pm doctor` on the only platform where
that entry resolves.
"""

from pm.install import _identity
from pm.lock import Lockfile


def test_identity_returns_none_for_digest_free_artifacts(tmp_path):
    lock = Lockfile(tmp_path / "lock.json")
    lock.set_pin(
        "termux-docker",
        "1.0",
        {"linux-arm64-bionic": {"url": "docker://termux/termux-docker@sha256:c14ffb70"}},
    )
    lock.save()
    assert _identity(lock, "termux-docker", "linux-arm64-bionic") is None


def test_identity_skips_digest_free_entries_inside_an_artifact_list(tmp_path):
    lock = Lockfile(tmp_path / "lock.json")
    lock.set_pin(
        "mixed",
        "1.0",
        {
            "linux-arm64": [
                {"url": "https://example.test/tool.tgz", "sha256": "a" * 64},
                {"url": "docker://example/mixed@sha256:abc"},
            ],
        },
    )
    lock.save()
    assert _identity(lock, "mixed", "linux-arm64") == ("linux-arm64", ("a" * 64,))


def test_identity_returns_none_when_lock_pins_no_artifacts(tmp_path):
    lock = Lockfile(tmp_path / "lock.json")
    lock.save()
    assert _identity(lock, "termux-docker", "linux-arm64-bionic") is None
