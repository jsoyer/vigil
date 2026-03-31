"""PWA assets -- manifest and service worker for installable dashboard."""

MANIFEST_JSON = """{
  "name": "USG Watchdog",
  "short_name": "Watchdog",
  "description": "Surveillance internet et reboot automatique USG",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0f1117",
  "theme_color": "#58a6ff",
  "icons": [
    {
      "src": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🛡</text></svg>",
      "sizes": "any",
      "type": "image/svg+xml"
    }
  ]
}"""

SERVICE_WORKER_JS = """
self.addEventListener('install', function(e) { self.skipWaiting(); });
self.addEventListener('activate', function(e) { self.clients.claim(); });
"""
