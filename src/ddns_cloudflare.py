"""DDNS Cloudflare -- automatic DNS record update when public IP changes.

Replaces the external shell script update-cloudflare-dns.sh.
Triggers: on recovery (after reboot/outage) + periodic check.
"""

import json
import logging
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass

from config import (
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_ZONE_ID,
    CLOUDFLARE_RECORD_NAMES,
    CLOUDFLARE_PROXIED,
    CLOUDFLARE_TTL,
    DDNS_CHECK_INTERVAL,
)

_IP_REGEX = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_IP_SERVICES = [
    "https://ifconfig.me/ip",
    "https://api.ipify.org",
    "https://checkip.amazonaws.com",
]

# Cache
_last_known_ip: str = ""
_last_check_time: float = 0.0


def is_configured() -> bool:
    """Check if Cloudflare DDNS is configured."""
    return bool(CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID and CLOUDFLARE_RECORD_NAMES)


@dataclass(frozen=True)
class DdnsResult:
    """Result of a DDNS update check."""

    current_ip: str
    previous_ip: str
    changed: bool
    records_updated: int
    records_failed: int
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "current_ip": self.current_ip,
            "previous_ip": self.previous_ip,
            "changed": self.changed,
            "records_updated": self.records_updated,
            "records_failed": self.records_failed,
            "errors": list(self.errors),
        }

    def summary(self) -> str:
        if not self.changed:
            return f"IP inchangee ({self.current_ip})"
        if self.records_failed == 0:
            return f"IP mise a jour : {self.previous_ip} -> {self.current_ip} ({self.records_updated} records)"
        return (
            f"IP changee : {self.previous_ip} -> {self.current_ip} "
            f"({self.records_updated} OK, {self.records_failed} echoues)"
        )


def get_public_ip(timeout: int = 10) -> str | None:
    """Get public IP from external service. Tries multiple providers.

    Returns IP string or None on failure. Never raises.
    """
    for url in _IP_SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vigil-ddns"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ip = resp.read().decode("utf-8").strip()
                if _IP_REGEX.match(ip):
                    return ip
        except Exception:
            continue

    logging.warning("DDNS: impossible de determiner l'IP publique")
    return None


def _cf_api(method: str, path: str, data: dict | None = None) -> dict | None:
    """Call Cloudflare API. Returns parsed JSON or None on error."""
    url = f"https://api.cloudflare.com/client/v4/{path}"
    body = json.dumps(data).encode("utf-8") if data else None

    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("success"):
                return result
            logging.warning("DDNS Cloudflare API error: %s", result.get("errors"))
            return None
    except urllib.error.HTTPError as e:
        logging.warning("DDNS Cloudflare HTTP %d", e.code)
        return None
    except Exception as e:
        logging.warning("DDNS Cloudflare error: %s", e)
        return None


def _get_record_id(zone_id: str, record_name: str) -> str | None:
    """Get the DNS record ID for a given name."""
    result = _cf_api("GET", f"zones/{zone_id}/dns_records?type=A&name={record_name}")
    if result and result.get("result"):
        records = result["result"]
        if records:
            return records[0].get("id")
    return None


def _update_record(zone_id: str, record_id: str, record_name: str, ip: str) -> bool:
    """Update a DNS A record with a new IP."""
    data = {
        "type": "A",
        "name": record_name,
        "content": ip,
        "ttl": CLOUDFLARE_TTL,
        "proxied": CLOUDFLARE_PROXIED,
    }
    result = _cf_api("PUT", f"zones/{zone_id}/dns_records/{record_id}", data)
    return result is not None


def check_and_update(force: bool = False) -> DdnsResult | None:
    """Check public IP and update Cloudflare DNS if changed.

    Args:
        force: Update records even if IP hasn't changed.

    Returns DdnsResult or None if not configured/IP unavailable. Never raises.
    """
    global _last_known_ip, _last_check_time

    if not is_configured():
        return None

    # Rate limit periodic checks
    now = time.time()
    if (
        not force
        and _last_check_time > 0
        and (now - _last_check_time) < DDNS_CHECK_INTERVAL
    ):
        return None
    _last_check_time = now

    # Get current public IP
    current_ip = get_public_ip()
    if current_ip is None:
        return None

    previous_ip = _last_known_ip or "unknown"

    # Check if IP changed
    if current_ip == _last_known_ip:
        logging.debug("DDNS: IP inchangee (%s)", current_ip)
        return DdnsResult(
            current_ip=current_ip,
            previous_ip=previous_ip,
            changed=False,
            records_updated=0,
            records_failed=0,
        )

    # IP changed -- update records
    _last_known_ip = current_ip
    logging.info("DDNS: IP changee %s -> %s", previous_ip, current_ip)

    records = [r.strip() for r in CLOUDFLARE_RECORD_NAMES.split(",") if r.strip()]
    updated = 0
    failed = 0
    errors: list[str] = []

    for record_name in records:
        record_id = _get_record_id(CLOUDFLARE_ZONE_ID, record_name)
        if record_id is None:
            logging.error("DDNS: record ID introuvable pour %s", record_name)
            errors.append(f"{record_name}: record ID introuvable")
            failed += 1
            continue

        if _update_record(CLOUDFLARE_ZONE_ID, record_id, record_name, current_ip):
            logging.info("DDNS: %s mis a jour -> %s", record_name, current_ip)
            updated += 1
        else:
            logging.error("DDNS: echec mise a jour %s", record_name)
            errors.append(f"{record_name}: update echoue")
            failed += 1

    return DdnsResult(
        current_ip=current_ip,
        previous_ip=previous_ip,
        changed=True,
        records_updated=updated,
        records_failed=failed,
        errors=tuple(errors),
    )
