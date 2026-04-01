"""Tests for src/backup_unifi.py"""

import subprocess
import time
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch, call

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# is_configured
# ---------------------------------------------------------------------------

class TestIsConfigured:
    def test_returns_true_when_dir_set(self):
        with patch("backup_unifi.UNIFI_BACKUP_DIR", "/some/dir"):
            from backup_unifi import is_configured
            assert is_configured() is True

    def test_returns_false_when_dir_empty(self):
        with patch("backup_unifi.UNIFI_BACKUP_DIR", ""):
            from backup_unifi import is_configured
            assert is_configured() is False


# ---------------------------------------------------------------------------
# find_latest_backup
# ---------------------------------------------------------------------------

class TestFindLatestBackup:
    def test_returns_none_when_not_configured(self):
        with patch("backup_unifi.UNIFI_BACKUP_DIR", ""):
            from backup_unifi import find_latest_backup
            assert find_latest_backup() is None

    def test_returns_none_when_dir_does_not_exist(self, tmp_path):
        nonexistent = str(tmp_path / "nonexistent")
        with patch("backup_unifi.UNIFI_BACKUP_DIR", nonexistent):
            from backup_unifi import find_latest_backup
            assert find_latest_backup() is None

    def test_returns_none_when_no_unf_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        with patch("backup_unifi.UNIFI_BACKUP_DIR", str(tmp_path)):
            from backup_unifi import find_latest_backup
            assert find_latest_backup() is None

    def test_returns_latest_unf_file(self, tmp_path):
        old = tmp_path / "backup_old.unf"
        new = tmp_path / "backup_new.unf"
        old.write_bytes(b"x" * 2000)
        new.write_bytes(b"x" * 2000)
        # Make old older than new
        os.utime(str(old), (time.time() - 7200, time.time() - 7200))
        os.utime(str(new), (time.time() - 10, time.time() - 10))
        with patch("backup_unifi.UNIFI_BACKUP_DIR", str(tmp_path)):
            from backup_unifi import find_latest_backup
            result = find_latest_backup()
            assert result is not None
            assert result.name == "backup_new.unf"

    def test_returns_only_unf_files(self, tmp_path):
        (tmp_path / "backup.unf").write_bytes(b"x" * 2000)
        (tmp_path / "notes.txt").write_text("ignored")
        with patch("backup_unifi.UNIFI_BACKUP_DIR", str(tmp_path)):
            from backup_unifi import find_latest_backup
            result = find_latest_backup()
            assert result is not None
            assert result.suffix == ".unf"


# ---------------------------------------------------------------------------
# check_backup_age
# ---------------------------------------------------------------------------

class TestCheckBackupAge:
    def test_fresh_backup_not_stale(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)
        with patch("backup_unifi.UNIFI_BACKUP_MAX_AGE_HOURS", 48):
            from backup_unifi import check_backup_age
            is_stale, age_hours = check_backup_age(f)
            assert is_stale is False
            assert age_hours == 0

    def test_old_backup_is_stale(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)
        old_time = time.time() - (72 * 3600)
        os.utime(str(f), (old_time, old_time))
        with patch("backup_unifi.UNIFI_BACKUP_MAX_AGE_HOURS", 48):
            from backup_unifi import check_backup_age
            is_stale, age_hours = check_backup_age(f)
            assert is_stale is True
            assert age_hours >= 72

    def test_exactly_at_boundary_not_stale(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)
        boundary_time = time.time() - (48 * 3600)
        os.utime(str(f), (boundary_time, boundary_time))
        with patch("backup_unifi.UNIFI_BACKUP_MAX_AGE_HOURS", 48):
            from backup_unifi import check_backup_age
            is_stale, age_hours = check_backup_age(f)
            # age_hours == 48 means > 48 is False
            assert is_stale is False


# ---------------------------------------------------------------------------
# check_backup_size
# ---------------------------------------------------------------------------

class TestCheckBackupSize:
    def test_healthy_size(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2048)
        from backup_unifi import check_backup_size
        is_suspicious, size = check_backup_size(f)
        assert is_suspicious is False
        assert size == 2048

    def test_suspicious_small_file(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 100)
        from backup_unifi import check_backup_size
        is_suspicious, size = check_backup_size(f)
        assert is_suspicious is True
        assert size == 100

    def test_empty_file_is_suspicious(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"")
        from backup_unifi import check_backup_size
        is_suspicious, size = check_backup_size(f)
        assert is_suspicious is True
        assert size == 0

    def test_exactly_1kb_not_suspicious(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 1024)
        from backup_unifi import check_backup_size
        is_suspicious, size = check_backup_size(f)
        assert is_suspicious is False
        assert size == 1024


# ---------------------------------------------------------------------------
# upload_backup
# ---------------------------------------------------------------------------

class TestUploadBackup:
    def test_success(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result), \
             patch("backup_unifi.UNIFI_BACKUP_RCLONE_DEST", "drive:Unifi"):
            from backup_unifi import upload_backup
            assert upload_backup(f) is True

    def test_rclone_nonzero_returncode(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error message"

        with patch("subprocess.run", return_value=mock_result):
            from backup_unifi import upload_backup
            assert upload_backup(f) is False

    def test_rclone_not_found(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)

        with patch("subprocess.run", side_effect=FileNotFoundError("rclone not found")):
            from backup_unifi import upload_backup
            assert upload_backup(f) is False

    def test_rclone_timeout(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="rclone", timeout=300)):
            from backup_unifi import upload_backup
            assert upload_backup(f) is False

    def test_generic_exception(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)

        with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
            from backup_unifi import upload_backup
            assert upload_backup(f) is False

    def test_uses_provided_destination(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 2000)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            from backup_unifi import upload_backup
            upload_backup(f, destination="s3:mybucket")
            cmd = mock_run.call_args[0][0]
            assert "s3:mybucket" in cmd


# ---------------------------------------------------------------------------
# prune_old_backups
# ---------------------------------------------------------------------------

class TestPruneOldBackups:
    def test_success(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result), \
             patch("backup_unifi.UNIFI_BACKUP_RETENTION_DAYS", 30), \
             patch("backup_unifi.UNIFI_BACKUP_RCLONE_DEST", "drive:Unifi"):
            from backup_unifi import prune_old_backups
            assert prune_old_backups() is True

    def test_failure_returns_false(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"

        with patch("subprocess.run", return_value=mock_result), \
             patch("backup_unifi.UNIFI_BACKUP_RETENTION_DAYS", 30):
            from backup_unifi import prune_old_backups
            assert prune_old_backups() is False

    def test_exception_returns_false(self):
        with patch("subprocess.run", side_effect=Exception("crash")):
            from backup_unifi import prune_old_backups
            assert prune_old_backups() is False

    def test_uses_retention_days_in_command(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("backup_unifi.UNIFI_BACKUP_RETENTION_DAYS", 14):
            from backup_unifi import prune_old_backups
            prune_old_backups("s3:bucket")
            cmd = mock_run.call_args[0][0]
            assert "14d" in cmd


# ---------------------------------------------------------------------------
# run_backup -- full pipeline
# ---------------------------------------------------------------------------

class TestRunBackup:
    def test_not_configured_returns_error(self):
        with patch("backup_unifi.UNIFI_BACKUP_DIR", ""):
            from backup_unifi import run_backup
            result = run_backup()
            assert result.ok is False
            assert "not configured" in result.error

    def test_no_backup_file_found(self, tmp_path):
        with patch("backup_unifi.UNIFI_BACKUP_DIR", str(tmp_path)):
            from backup_unifi import run_backup
            result = run_backup()
            assert result.ok is False
            assert ".unf" in result.error

    def test_suspicious_size_returns_error(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 100)
        with patch("backup_unifi.UNIFI_BACKUP_DIR", str(tmp_path)), \
             patch("backup_unifi.UNIFI_BACKUP_MAX_AGE_HOURS", 48), \
             patch("backup_unifi.UNIFI_BACKUP_RCLONE_DEST", "drive:Unifi"):
            from backup_unifi import run_backup
            result = run_backup()
            assert result.ok is False
            assert "suspect" in result.error

    def test_upload_failure_returns_error(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 5000)
        with patch("backup_unifi.UNIFI_BACKUP_DIR", str(tmp_path)), \
             patch("backup_unifi.UNIFI_BACKUP_MAX_AGE_HOURS", 48), \
             patch("backup_unifi.UNIFI_BACKUP_RCLONE_DEST", "drive:Unifi"), \
             patch("backup_unifi.upload_backup", return_value=False):
            from backup_unifi import run_backup
            result = run_backup()
            assert result.ok is False
            assert "rclone" in result.error

    def test_success_pipeline(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 5000)
        with patch("backup_unifi.UNIFI_BACKUP_DIR", str(tmp_path)), \
             patch("backup_unifi.UNIFI_BACKUP_MAX_AGE_HOURS", 48), \
             patch("backup_unifi.UNIFI_BACKUP_RCLONE_DEST", "drive:Unifi"), \
             patch("backup_unifi.upload_backup", return_value=True), \
             patch("backup_unifi.prune_old_backups", return_value=True):
            from backup_unifi import run_backup
            result = run_backup(source="test")
            assert result.ok is True
            assert result.filename == "backup.unf"
            assert result.size_bytes == 5000

    def test_stale_backup_still_uploads(self, tmp_path):
        f = tmp_path / "backup.unf"
        f.write_bytes(b"x" * 5000)
        old_time = time.time() - (72 * 3600)
        os.utime(str(f), (old_time, old_time))
        with patch("backup_unifi.UNIFI_BACKUP_DIR", str(tmp_path)), \
             patch("backup_unifi.UNIFI_BACKUP_MAX_AGE_HOURS", 48), \
             patch("backup_unifi.UNIFI_BACKUP_RCLONE_DEST", "drive:Unifi"), \
             patch("backup_unifi.upload_backup", return_value=True), \
             patch("backup_unifi.prune_old_backups", return_value=True):
            from backup_unifi import run_backup
            result = run_backup()
            assert result.ok is True
            assert result.stale is True


# ---------------------------------------------------------------------------
# BackupResult helpers
# ---------------------------------------------------------------------------

class TestBackupResult:
    def test_summary_ok(self):
        from backup_unifi import BackupResult
        r = BackupResult(ok=True, filename="f.unf", size_bytes=2097152, destination="drive:Unifi")
        s = r.summary()
        assert "Backup OK" in s
        assert "f.unf" in s
        assert "2.0 MB" in s

    def test_summary_error(self):
        from backup_unifi import BackupResult
        r = BackupResult(ok=False, error="something broke")
        s = r.summary()
        assert "echoue" in s
        assert "something broke" in s

    def test_to_dict_no_stale(self):
        from backup_unifi import BackupResult
        r = BackupResult(ok=True, filename="f.unf", size_bytes=1048576, destination="s3:b")
        d = r.to_dict()
        assert d["ok"] is True
        assert d["size_mb"] == 1.0
        assert "stale" not in d
        assert "error" not in d

    def test_to_dict_with_stale(self):
        from backup_unifi import BackupResult
        r = BackupResult(ok=True, filename="f.unf", size_bytes=1024, destination="s3:b", stale=True, stale_hours=72)
        d = r.to_dict()
        assert d["stale"] is True
        assert d["stale_hours"] == 72

    def test_to_dict_with_error(self):
        from backup_unifi import BackupResult
        r = BackupResult(ok=False, error="boom")
        d = r.to_dict()
        assert d["error"] == "boom"
