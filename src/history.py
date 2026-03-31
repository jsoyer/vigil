"""History -- ring buffer for time-series data points (score, latency)."""

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class DataPoint:
    ts: float
    score: int
    gateway_rtt: float | None
    internet_rtt: float | None
    download_mbps: float | None = None


class HistoryBuffer:
    """Thread-safe ring buffer storing the last N data points."""

    def __init__(self, max_points: int = 240) -> None:
        # 240 points * 30s interval = 2 hours
        self._points: deque[DataPoint] = deque(maxlen=max_points)
        self._lock = threading.Lock()

    def record(
        self,
        score: int,
        gateway_rtt: float | None,
        internet_rtt: float | None,
        download_mbps: float | None = None,
    ) -> None:
        point = DataPoint(
            ts=time.time(),
            score=score,
            gateway_rtt=round(gateway_rtt, 1) if gateway_rtt is not None else None,
            internet_rtt=round(internet_rtt, 1) if internet_rtt is not None else None,
            download_mbps=round(download_mbps, 2) if download_mbps is not None else None,
        )
        with self._lock:
            self._points.append(point)

    def get_all(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "ts": p.ts,
                    "score": p.score,
                    "gw_rtt": p.gateway_rtt,
                    "inet_rtt": p.internet_rtt,
                    "dl_mbps": p.download_mbps,
                }
                for p in self._points
            ]
