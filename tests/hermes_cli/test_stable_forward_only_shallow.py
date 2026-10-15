"""An unchosen default channel never moves a checkout backward on a guess."""
import subprocess

import pytest

from hermes_cli import source_check, source_releases


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def history(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    shas = []
    for n in range(3):
        (origin / "f").write_text(str(n))
        _git(origin, "add", "f")
        _git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", str(n))
        shas.append(_git(origin, "rev-parse", "HEAD"))
    return origin, shas  # shas[0] is the "release", HEAD (shas[2]) is ahead of it


@pytest.mark.parametrize("release_fetched", [False, True])
@pytest.mark.parametrize("compare", [None, {"status": "ahead"}])
def test_shallow_checkout_ahead_of_release_stays_put(history, tmp_path, monkeypatch, compare, release_fetched):
    origin, shas = history
    clone = tmp_path / "shallow"
    _git(tmp_path, "clone", "-q", "--depth", "1", f"file://{origin}", str(clone))
    if release_fetched:  # present but cut off by the shallow boundary: is-ancestor exits 1
        _git(origin, "tag", "v0.0.1", shas[0])
        _git(clone, "fetch", "-q", "--depth", "1", "origin", "tag", "v0.0.1")
    monkeypatch.setattr(source_check, "_github_compare", lambda *a, **k: compare)
    # Shallow history hides the release commit: unknown (or proven ahead) keeps HEAD.
    assert source_releases._head_containing(["git"], clone, shas[0], "o/r") == shas[2]
    # GitHub proving HEAD is behind the release is the only case that moves it.
    monkeypatch.setattr(source_check, "_github_compare", lambda *a, **k: {"status": "behind"})
    assert source_releases._head_containing(["git"], clone, shas[0], "o/r") is None


def test_full_history_behind_release_is_proof(history, tmp_path, monkeypatch):
    origin, shas = history
    clone = tmp_path / "full"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    _git(clone, "checkout", "-q", shas[0])
    monkeypatch.setattr(source_check, "_github_compare", lambda *a, **k: pytest.fail("no network on proof"))
    assert source_releases._head_containing(["git"], clone, shas[2], "o/r") is None
    assert source_releases._head_containing(["git"], clone, shas[0], "o/r") == shas[0]


def test_ancestry_probe_that_times_out_keeps_head(history, tmp_path, monkeypatch):
    """A merge-base that cannot finish is an unknown relation, not a failed update (#138716).

    The reporter's ``hermes update`` died on "Could not resolve the stable source channel:
    ... timed out after 10 seconds": the probe's TimeoutExpired escaped ``_head_containing``
    and aborted the channel resolution. HEAD itself stays the answer the code documents.
    """
    origin, shas = history
    clone = tmp_path / "full-timeout"
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    real_run = subprocess.run

    def slow(args, *a, **k):
        if list(args)[1:3] == ["merge-base", "--is-ancestor"]:
            raise subprocess.TimeoutExpired(args, 10)
        return real_run(args, *a, **k)

    monkeypatch.setattr(source_releases.subprocess, "run", slow)
    # GitHub unreachable too: still unknown, so still HEAD.
    monkeypatch.setattr(source_check, "_github_compare", lambda *a, **k: None)
    assert source_releases._head_containing(["git"], clone, shas[0], "o/r") == shas[2]
    # A proven "behind" verdict still decides when the local probe could not.
    monkeypatch.setattr(source_check, "_github_compare", lambda *a, **k: {"status": "behind"})
    assert source_releases._head_containing(["git"], clone, shas[0], "o/r") is None
