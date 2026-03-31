"""Mini speedtest -- lightweight download speed measurement."""

import logging
import time
import urllib.request
import urllib.error
from dataclasses import dataclass

from config import CHECK_INTERVAL

# Small test files from well-known CDNs (kept small to minimize bandwidth)
_TEST_URLS = [
    "http://speed.cloudflare.com/__down?bytes=100000",  # 100KB from Cloudflare
]

# How often to run (every N check cycles, default every 10 min)
SPEEDTEST_INTERVAL_CYCLES = max(1, 600 // CHECK_INTERVAL)


@dataclass(frozen=True)
class SpeedtestResult:
    """Result of a download speed test."""
    download_mbps: float | None = None
    duration_ms: int | None = None
    url: str = ""
    ok: bool = False

    def to_dict(self) -> dict:
        return {
            "download_mbps": round(self.download_mbps, 2) if self.download_mbps else None,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
        }


def run_speedtest(url: str | None = None, timeout: int = 15) -> SpeedtestResult:
    """Download a small file and measure speed.

    Returns SpeedtestResult. Never raises.
    """
    if url is None:
        url = _TEST_URLS[0]

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "usg-watchdog-speedtest"})
        start = time.monotonic()

        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()

        elapsed = time.monotonic() - start
        bytes_downloaded = len(data)

        if elapsed > 0:
            mbps = (bytes_downloaded * 8) / (elapsed * 1_000_000)
        else:
            mbps = 0.0

        logging.debug(
            "Speedtest: %.2f Mbps (%d bytes in %dms)",
            mbps, bytes_downloaded, int(elapsed * 1000),
        )

        return SpeedtestResult(
            download_mbps=mbps,
            duration_ms=int(elapsed * 1000),
            url=url,
            ok=True,
        )

    except urllib.error.URLError as e:
        logging.debug("Speedtest echoue: %s", e)
        return SpeedtestResult(url=url or "")
    except Exception as e:
        logging.debug("Speedtest erreur: %s", e)
        return SpeedtestResult(url=url or "")
