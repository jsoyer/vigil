"""Tests for pwa.py -- PWA manifest and service worker assets."""

import json

import pytest

from src.pwa import MANIFEST_JSON, SERVICE_WORKER_JS


class TestManifestJson:
    def test_is_valid_json(self):
        parsed = json.loads(MANIFEST_JSON)
        assert isinstance(parsed, dict)

    def test_contains_name_field(self):
        parsed = json.loads(MANIFEST_JSON)
        assert "name" in parsed
        assert parsed["name"] == "Vigil"

    def test_contains_short_name(self):
        parsed = json.loads(MANIFEST_JSON)
        assert "short_name" in parsed
        assert isinstance(parsed["short_name"], str)
        assert len(parsed["short_name"]) > 0

    def test_contains_start_url(self):
        parsed = json.loads(MANIFEST_JSON)
        assert "start_url" in parsed
        assert parsed["start_url"] == "/"

    def test_contains_display_field(self):
        parsed = json.loads(MANIFEST_JSON)
        assert "display" in parsed
        assert parsed["display"] in (
            "standalone",
            "fullscreen",
            "minimal-ui",
            "browser",
        )

    def test_contains_background_color(self):
        parsed = json.loads(MANIFEST_JSON)
        assert "background_color" in parsed
        assert parsed["background_color"].startswith("#")

    def test_contains_theme_color(self):
        parsed = json.loads(MANIFEST_JSON)
        assert "theme_color" in parsed
        assert parsed["theme_color"].startswith("#")

    def test_contains_icons_array(self):
        parsed = json.loads(MANIFEST_JSON)
        assert "icons" in parsed
        assert isinstance(parsed["icons"], list)
        assert len(parsed["icons"]) >= 1

    def test_icons_have_required_fields(self):
        parsed = json.loads(MANIFEST_JSON)
        for icon in parsed["icons"]:
            assert "src" in icon
            assert "sizes" in icon

    def test_is_non_empty_string(self):
        assert isinstance(MANIFEST_JSON, str)
        assert len(MANIFEST_JSON.strip()) > 0


class TestServiceWorkerJs:
    def test_is_non_empty_string(self):
        assert isinstance(SERVICE_WORKER_JS, str)
        assert len(SERVICE_WORKER_JS.strip()) > 0

    def test_contains_install_event_listener(self):
        assert "install" in SERVICE_WORKER_JS

    def test_contains_activate_event_listener(self):
        assert "activate" in SERVICE_WORKER_JS

    def test_contains_skip_waiting(self):
        assert "skipWaiting" in SERVICE_WORKER_JS

    def test_contains_clients_claim(self):
        assert "clients.claim" in SERVICE_WORKER_JS

    def test_uses_add_event_listener_pattern(self):
        assert "addEventListener" in SERVICE_WORKER_JS
