"""Tests for updater/update.py -- version parsing, tag filtering, validation."""

import sys
import os

# Add updater to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "updater"))

from update import (
    parse_version,
    is_stable_tag,
    is_dev_tag,
    find_latest_tag,
    validate_syntax,
    extract_tarball,
)


class TestParseVersion:
    def test_simple(self):
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self):
        assert parse_version("v1.2.3") == (1, 2, 3)

    def test_with_prerelease(self):
        assert parse_version("v1.2.3-dev.1") == (1, 2, 3)

    def test_comparison(self):
        assert parse_version("1.1.0") > parse_version("1.0.9")
        assert parse_version("2.0.0") > parse_version("1.99.99")
        assert parse_version("1.0.0") == parse_version("v1.0.0")

    def test_invalid(self):
        assert parse_version("invalid") == (0, 0, 0)


class TestTagFiltering:
    def test_stable_tags(self):
        assert is_stable_tag("v1.0.0") is True
        assert is_stable_tag("v1.2.3") is True
        assert is_stable_tag("v10.20.30") is True

    def test_stable_rejects_dev(self):
        assert is_stable_tag("v1.0.0-dev.1") is False
        assert is_stable_tag("v1.0.0-rc.1") is False

    def test_stable_rejects_invalid(self):
        assert is_stable_tag("1.0.0") is False
        assert is_stable_tag("release-1.0") is False

    def test_dev_tags(self):
        assert is_dev_tag("v1.0.0-dev.1") is True
        assert is_dev_tag("v1.0.0-rc.1") is True

    def test_dev_rejects_stable(self):
        assert is_dev_tag("v1.0.0") is False


class TestFindLatestTag:
    def test_finds_latest_stable(self):
        tags = [
            {"name": "v1.0.0"},
            {"name": "v1.1.0"},
            {"name": "v1.0.1"},
            {"name": "v1.1.0-dev.1"},
        ]
        # Mock UPDATE_CHANNEL to stable
        import update
        original = update.UPDATE_CHANNEL
        update.UPDATE_CHANNEL = "stable"
        try:
            result = find_latest_tag(tags)
            assert result is not None
            assert result["name"] == "v1.1.0"
        finally:
            update.UPDATE_CHANNEL = original

    def test_finds_latest_dev(self):
        tags = [
            {"name": "v1.0.0"},
            {"name": "v1.0.0-dev.1"},
            {"name": "v1.1.0-dev.1"},
            {"name": "v1.0.0-rc.1"},
        ]
        import update
        original = update.UPDATE_CHANNEL
        update.UPDATE_CHANNEL = "dev"
        try:
            result = find_latest_tag(tags)
            assert result is not None
            # v1.1.0-dev.1 has highest base version among dev tags
            assert result["name"] == "v1.1.0-dev.1"
        finally:
            update.UPDATE_CHANNEL = original

    def test_returns_none_when_no_match(self):
        tags = [{"name": "v1.0.0-dev.1"}]
        import update
        original = update.UPDATE_CHANNEL
        update.UPDATE_CHANNEL = "stable"
        try:
            assert find_latest_tag(tags) is None
        finally:
            update.UPDATE_CHANNEL = original

    def test_empty_tags(self):
        assert find_latest_tag([]) is None


class TestValidateSyntax:
    def test_valid_python(self, tmp_path):
        (tmp_path / "good.py").write_text("x = 1\n")
        assert validate_syntax(tmp_path) is True

    def test_invalid_python(self, tmp_path):
        (tmp_path / "bad.py").write_text("def f(\n")
        assert validate_syntax(tmp_path) is False

    def test_empty_directory(self, tmp_path):
        assert validate_syntax(tmp_path) is False
