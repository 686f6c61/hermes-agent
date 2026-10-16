"""A retired-WAL generation directory is pruned at directory level, not left to the file rules.

``<name>.retired-wal-<ts>-<pid>/`` holds a full ``state.db`` copy plus its manifest: the capture
is meant to be excluded whole, and the backup walk used to descend into it. The inner
``state.db`` then goes through the strict SQLite snapshot, which fails, and one failure discards
the entire pre-update archive (``_db_failure`` -> ``_SQLiteSnapshotError``). The exclusion in
``_EXCLUDED_PREFIXES`` only ever matched file basenames, so the directory form was walked.
"""

from pathlib import Path

from hermes_cli.backup import _iter_backup_files

RETIRED_DIR = "state.db.retired-wal-20261011-205050-4478"


def _write(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


class TestRetiredWalGenerationPrune:
    def test_retired_wal_generation_dir_is_never_walked(self, tmp_path):
        """Root-level and per-profile retired generations both stay out of the archive."""
        root = tmp_path / ".hermes"
        root.mkdir()
        files = {
            f"{RETIRED_DIR}/state.db": False,
            f"{RETIRED_DIR}/manifest.json": False,
            f"{RETIRED_DIR}/state.db-wal": False,
            f"profiles/coder/{RETIRED_DIR}/state.db": False,
            "state.db": True,
            "config.yaml": True,
            "skills/example/SKILL.md": True,
        }
        for rel in files:
            _write(root, rel)

        skipped: set = set()
        selected = {str(rel) for _, rel in _iter_backup_files(root, tmp_path / "out.zip", skipped)}

        assert selected == {rel for rel, keep in files.items() if keep}
        assert RETIRED_DIR in skipped
        assert str(Path("profiles/coder") / RETIRED_DIR) in skipped

    def test_pre_update_emergency_dir_is_pruned_too(self, tmp_path):
        """The same prefix rule covers the desktop updater's pre-flight directory."""
        root = tmp_path / ".hermes"
        root.mkdir()
        _write(root, "state.db.pre-update-emergency-20261011-205050/state.db")
        _write(root, "config.yaml")

        selected = {str(rel) for _, rel in _iter_backup_files(root, tmp_path / "out.zip")}

        assert selected == {"config.yaml"}

    def test_plain_retired_wal_file_stays_excluded(self, tmp_path):
        """The basename fallback still drops a retired generation stored as a plain file."""
        root = tmp_path / ".hermes"
        root.mkdir()
        _write(root, f"{RETIRED_DIR}.bak")
        _write(root, "state.db.pre-update-emergency-20261011-205050.bak")
        _write(root, "state.db")

        selected = {str(rel) for _, rel in _iter_backup_files(root, tmp_path / "out.zip")}

        assert selected == {"state.db"}

    def test_a_similar_directory_is_kept(self, tmp_path):
        """Only the retired-generation prefix is pruned: a user dir with a close name survives."""
        root = tmp_path / ".hermes"
        root.mkdir()
        _write(root, "state.db.retired-wal/state.db")
        _write(root, "state.db.keep/notes.txt")

        selected = {str(rel) for _, rel in _iter_backup_files(root, tmp_path / "out.zip")}

        assert selected == {
            "state.db.retired-wal/state.db",
            "state.db.keep/notes.txt",
        }
