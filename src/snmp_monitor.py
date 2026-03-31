"""SNMP monitor -- read USG health metrics (CPU, memory, temperature)."""

import logging
import subprocess
from dataclasses import dataclass

from config import USG_IP


@dataclass(frozen=True)
class UsgMetrics:
    """USG health metrics via SNMP."""
    cpu_percent: float | None = None
    memory_percent: float | None = None
    uptime_seconds: int | None = None
    reachable: bool = False

    def to_dict(self) -> dict:
        return {
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "uptime_seconds": self.uptime_seconds,
            "reachable": self.reachable,
        }

    def is_stressed(self, cpu_threshold: float = 90.0, mem_threshold: float = 90.0) -> bool:
        """Check if USG is under stress."""
        if self.cpu_percent is not None and self.cpu_percent > cpu_threshold:
            return True
        if self.memory_percent is not None and self.memory_percent > mem_threshold:
            return True
        return False


# Standard OIDs
_OID_UPTIME = "1.3.6.1.2.1.1.3.0"           # sysUpTime (timeticks)
_OID_CPU_1MIN = "1.3.6.1.4.1.2021.11.9.0"   # ssCpuUser (UCD-SNMP)
_OID_MEM_TOTAL = "1.3.6.1.4.1.2021.4.5.0"   # memTotalReal
_OID_MEM_AVAIL = "1.3.6.1.4.1.2021.4.6.0"   # memAvailReal


def _snmpget(oid: str, host: str = USG_IP, community: str = "public", timeout: int = 5) -> str | None:
    """Run snmpget and return the value string. Returns None on failure."""
    try:
        result = subprocess.run(
            ["snmpget", "-v2c", "-c", community, "-t", str(timeout), "-r", "1", host, oid],
            capture_output=True,
            text=True,
            timeout=timeout + 3,
        )
        if result.returncode != 0:
            return None
        # Parse "OID = TYPE: VALUE" format
        output = result.stdout.strip()
        if ":" in output:
            return output.split(":", 1)[1].strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    except Exception as e:
        logging.debug("SNMP error %s: %s", oid, e)
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.split()[0])
    except (ValueError, IndexError):
        return None


def read_usg_metrics(host: str = USG_IP, community: str = "public") -> UsgMetrics:
    """Read USG health metrics via SNMP. Never raises.

    Requires snmpget installed (apt install snmp).
    """
    uptime_raw = _snmpget(_OID_UPTIME, host, community)
    if uptime_raw is None:
        return UsgMetrics(reachable=False)

    # Parse uptime (timeticks in hundredths of a second)
    uptime_ticks = _parse_int(uptime_raw)
    uptime_secs = uptime_ticks // 100 if uptime_ticks is not None else None

    # CPU
    cpu_raw = _snmpget(_OID_CPU_1MIN, host, community)
    cpu_pct = None
    if cpu_raw is not None:
        v = _parse_int(cpu_raw)
        if v is not None:
            cpu_pct = float(v)

    # Memory
    mem_total_raw = _snmpget(_OID_MEM_TOTAL, host, community)
    mem_avail_raw = _snmpget(_OID_MEM_AVAIL, host, community)
    mem_pct = None
    mem_total = _parse_int(mem_total_raw)
    mem_avail = _parse_int(mem_avail_raw)
    if mem_total and mem_avail and mem_total > 0:
        mem_pct = round(((mem_total - mem_avail) / mem_total) * 100, 1)

    return UsgMetrics(
        cpu_percent=cpu_pct,
        memory_percent=mem_pct,
        uptime_seconds=uptime_secs,
        reachable=True,
    )
