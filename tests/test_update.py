"""Tests for updater/update.py -- health_check() only (Bug 1: version mismatch
after restart must be treated as an update failure, not silently reported as
success). See docs/tasks/router/bugfix/2026-08-23_1000-vigil-identity-systemd-layout.md
"""

import subprocess
import sys
import os
from unittest.mock import patch, MagicMock

# Add updater to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))

import update
from update import health_check, install_requirements, update_own_copy


def _mock_response(payload: bytes):
    """Build a mock urlopen() return value usable as a context manager."""
    resp = MagicMock()
    resp.read.return_value = payload
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestHealthCheckSuccess:
    def test_version_matches_status_healthy(self):
        payload = b'{"status": "healthy", "version": "1.8.2"}'
        with patch(
            "update.urllib.request.urlopen", return_value=_mock_response(payload)
        ):
            assert health_check("1.8.2") is True

    def test_version_matches_status_degraded(self):
        payload = b'{"status": "degraded", "version": "1.8.2"}'
        with patch(
            "update.urllib.request.urlopen", return_value=_mock_response(payload)
        ):
            assert health_check("1.8.2") is True


class TestHealthCheckVersionMismatch:
    def test_version_mismatch_even_if_healthy_returns_false(self):
        """Core regression test: the service is healthy but still running the
        old code -- must be reported as a failed update, immediately, not
        retried until timeout."""
        payload = b'{"status": "healthy", "version": "1.8.1"}'
        with patch(
            "update.urllib.request.urlopen", return_value=_mock_response(payload)
        ):
            with patch("update.time.sleep") as mock_sleep:
                assert health_check("1.8.2") is False
                # Must fail fast on mismatch, not loop sleeping until deadline.
                mock_sleep.assert_not_called()


class TestHealthCheckTimeoutAndErrors:
    def test_status_never_healthy_times_out(self):
        payload = b'{"status": "starting", "version": "1.8.2"}'
        with patch("update.HEALTH_CHECK_TIMEOUT", 0.2):
            with patch(
                "update.urllib.request.urlopen", return_value=_mock_response(payload)
            ):
                with patch("update.time.sleep"):
                    assert health_check("1.8.2") is False

    def test_urlopen_always_raises_returns_false(self):
        with patch("update.HEALTH_CHECK_TIMEOUT", 0.2):
            with patch(
                "update.urllib.request.urlopen",
                side_effect=Exception("connection refused"),
            ):
                with patch("update.time.sleep"):
                    assert health_check("1.8.2") is False


class TestInstallRequirementsSuccess:
    def test_requirements_present_pip_succeeds(self, tmp_path):
        staged_dir = tmp_path / "staged"
        staged_dir.mkdir()
        requirements_file = staged_dir / "requirements.txt"
        requirements_file.write_text("requests==2.31.0\n")

        fake_pip = tmp_path / "venv" / "bin" / "pip"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Successfully installed requests-2.31.0"
        mock_result.stderr = ""

        with patch("update.VENV_PIP", fake_pip):
            with patch("update.subprocess.run", return_value=mock_result) as mock_run:
                assert install_requirements(staged_dir) is True

        mock_run.assert_called_once_with(
            [str(fake_pip), "install", "-r", str(requirements_file)],
            capture_output=True,
            text=True,
            timeout=update.PIP_INSTALL_TIMEOUT,
        )


class TestInstallRequirementsFailure:
    def test_pip_returns_nonzero_returns_false(self, tmp_path):
        staged_dir = tmp_path / "staged"
        staged_dir.mkdir()
        (staged_dir / "requirements.txt").write_text("requests==2.31.0\n")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "ERROR: could not find a version"

        with patch("update.subprocess.run", return_value=mock_result):
            assert install_requirements(staged_dir) is False

    def test_pip_timeout_returns_false(self, tmp_path):
        staged_dir = tmp_path / "staged"
        staged_dir.mkdir()
        (staged_dir / "requirements.txt").write_text("requests==2.31.0\n")

        with patch(
            "update.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=300),
        ):
            assert install_requirements(staged_dir) is False

    def test_pip_missing_binary_oserror_returns_false(self, tmp_path):
        staged_dir = tmp_path / "staged"
        staged_dir.mkdir()
        (staged_dir / "requirements.txt").write_text("requests==2.31.0\n")

        with patch("update.subprocess.run", side_effect=OSError("no such file")):
            assert install_requirements(staged_dir) is False


class TestInstallRequirementsNoOp:
    def test_no_requirements_file_returns_true_without_calling_pip(self, tmp_path):
        staged_dir = tmp_path / "staged"
        staged_dir.mkdir()
        # No requirements.txt created -- true no-op.

        with patch("update.subprocess.run") as mock_run:
            assert install_requirements(staged_dir) is True

        mock_run.assert_not_called()


class TestUpdateOwnCopyPresent:
    def test_updater_dir_present_copies_py_files(self, tmp_path):
        release_dir = tmp_path / "release"
        staged_updater = release_dir / "updater"
        staged_updater.mkdir(parents=True)
        (staged_updater / "update.py").write_text("# new update.py\n")
        (staged_updater / "preflight.py").write_text("# new preflight.py\n")
        (staged_updater / "README.md").write_text("not python -- must be ignored\n")

        dest_dir = tmp_path / "install" / "updater"

        with patch("update.INSTALL_DIR", tmp_path / "install"):
            update_own_copy(release_dir)

        assert (dest_dir / "update.py").read_text() == "# new update.py\n"
        assert (dest_dir / "preflight.py").read_text() == "# new preflight.py\n"
        assert not (dest_dir / "README.md").exists()


class TestUpdateOwnCopyAbsent:
    def test_no_updater_dir_in_release_is_noop(self, tmp_path):
        release_dir = tmp_path / "release"
        release_dir.mkdir()
        # No updater/ subdirectory -- release predates this feature, or the
        # release simply doesn't ship one.

        dest_dir = tmp_path / "install" / "updater"

        with patch("update.INSTALL_DIR", tmp_path / "install"):
            update_own_copy(release_dir)

        assert not dest_dir.exists()


class TestUpdateOwnCopyFailure:
    def test_copy_error_is_warning_not_exception(self, tmp_path, caplog):
        release_dir = tmp_path / "release"
        staged_updater = release_dir / "updater"
        staged_updater.mkdir(parents=True)
        (staged_updater / "update.py").write_text("# new update.py\n")

        with patch("update.INSTALL_DIR", tmp_path / "install"):
            with patch("update.shutil.copy2", side_effect=OSError("disk full")):
                with caplog.at_level("WARNING", logger="updater"):
                    # Must not raise -- a copy failure degrades to a warning,
                    # it is never treated as an update failure.
                    update_own_copy(release_dir)

        assert any("copie updater" in rec.message.lower() for rec in caplog.records)
