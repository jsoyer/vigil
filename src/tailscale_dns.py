"""Tailscale DNS sync -- sync Tailscale device IPs to Cloudflare DNS records.

Creates A records for each Tailscale device: hostname.domain or hostname.subdomain.domain.
Removes orphaned records when devices leave the tailnet.

Optional module: inert if TAILSCALE_API_KEY is not configured.
"""

import ipaddress
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
    CLOUDFLARE_TTL,
    TAILSCALE_API_KEY,
    TAILSCALE_TAILNET,
    TAILSCALE_DNS_SUBDOMAIN,
    TAILSCALE_DNS_PREFIX,
    TAILSCALE_DNS_POSTFIX,
    TAILSCALE_SYNC_INTERVAL,
)

_TS_IPV4_RANGE = ipaddress.IPv4Network("100.64.0.0/10")
_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9.\-]+$")
_CF_API = "https://api.cloudflare.com/client/v4"
_TS_API = "https://api.tailscale.com/api/v2"

_last_sync_time: float = 0.0


def is_configured() -> bool:
    return bool(
        TAILSCALE_API_KEY
        and TAILSCALE_TAILNET
        and CLOUDFLARE_API_TOKEN
        and CLOUDFLARE_ZONE_ID
    )


@dataclass(frozen=True)
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    errors: int = 0
    ok: bool = True

    def summary(self) -> str:
        parts = []
        if self.created:
            parts.append(f"{self.created} crees")
        if self.updated:
            parts.append(f"{self.updated} mis a jour")
        if self.deleted:
            parts.append(f"{self.deleted} supprimes")
        if self.unchanged:
            parts.append(f"{self.unchanged} inchanges")
        if self.errors:
            parts.append(f"{self.errors} erreurs")
        return (
            "Tailscale DNS sync : " + ", ".join(parts)
            if parts
            else "Tailscale DNS sync : rien a faire"
        )

    def to_dict(self) -> dict:
        return {
            "created": self.created,
            "updated": self.updated,
            "deleted": self.deleted,
            "unchanged": self.unchanged,
            "errors": self.errors,
            "ok": self.ok,
        }


def _cf_request(method: str, path: str, data: dict | None = None) -> dict | None:
    """Cloudflare API request."""
    url = f"{_CF_API}/{path}"
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
            return None
    except Exception:
        return None


def _ts_get_devices() -> list[dict] | None:
    """Get Tailscale devices with their IPs."""
    url = f"{_TS_API}/tailnet/{TAILSCALE_TAILNET}/devices"

    # Basic auth with API key
    import base64

    auth = base64.b64encode(f"{TAILSCALE_API_KEY}:".encode()).decode()

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Basic {auth}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            devices = []
            for device in data.get("devices", []):
                hostname = device.get("hostname", "").lower()
                name = device.get("name", "").split(".")[0].lower()
                for addr in device.get("addresses", []):
                    try:
                        ip = ipaddress.ip_address(addr)
                        if ip.version == 4 and ip in _TS_IPV4_RANGE:
                            devices.append({"hostname": hostname, "ip": addr})
                            if name != hostname:
                                devices.append({"hostname": name, "ip": addr})
                    except ValueError:
                        continue
            return devices
    except Exception as e:
        logging.warning("Tailscale API error: %s", e)
        return None


def _build_fqdn(hostname: str) -> str:
    """Build FQDN from hostname and config."""
    name = f"{TAILSCALE_DNS_PREFIX}{hostname}{TAILSCALE_DNS_POSTFIX}"
    # Get domain from zone -- we use the records directly
    if TAILSCALE_DNS_SUBDOMAIN:
        return f"{name}.{TAILSCALE_DNS_SUBDOMAIN}"
    return name


def _get_zone_records() -> list[dict]:
    """Get all A records in the zone."""
    records = []
    page = 1
    while True:
        result = _cf_request(
            "GET",
            f"zones/{CLOUDFLARE_ZONE_ID}/dns_records?type=A&per_page=100&page={page}",
        )
        if not result:
            break
        records.extend(result.get("result", []))
        total_pages = result.get("result_info", {}).get("total_pages", 1)
        if page >= total_pages:
            break
        page += 1
    return records


def sync_tailscale_dns(force: bool = False) -> SyncResult | None:
    """Sync Tailscale device IPs to Cloudflare DNS.

    Returns SyncResult or None if not configured or rate-limited.
    Never raises.
    """
    global _last_sync_time

    if not is_configured():
        return None

    now = time.time()
    if (
        not force
        and _last_sync_time > 0
        and (now - _last_sync_time) < TAILSCALE_SYNC_INTERVAL
    ):
        return None
    _last_sync_time = now

    # Get Tailscale devices
    devices = _ts_get_devices()
    if devices is None:
        return SyncResult(ok=False, errors=1)

    # Build desired state: {fqdn: ip}
    desired: dict[str, str] = {}
    for dev in devices:
        if not _HOSTNAME_RE.match(dev["hostname"]):
            continue
        fqdn = _build_fqdn(dev["hostname"])
        desired[fqdn] = dev["ip"]

    # Get current Cloudflare records
    cf_records = _get_zone_records()

    # Index existing records by name
    existing: dict[str, dict] = {}
    for rec in cf_records:
        name_part = (
            rec["name"].split(f".{TAILSCALE_DNS_SUBDOMAIN}")[0]
            if TAILSCALE_DNS_SUBDOMAIN
            else rec["name"].split(".")[0]
        )
        # Only manage records with our prefix/postfix
        if TAILSCALE_DNS_PREFIX and not name_part.startswith(TAILSCALE_DNS_PREFIX):
            continue
        # Only manage Tailscale IPs
        try:
            ip = ipaddress.ip_address(rec["content"])
            if ip not in _TS_IPV4_RANGE:
                continue
        except ValueError:
            continue
        existing[rec["name"]] = rec

    created = 0
    updated = 0
    deleted = 0
    unchanged = 0
    errors = 0

    # Create/update records
    for fqdn, ip in desired.items():
        # Find full record name in CF
        full_name = None
        for rec_name in existing:
            if rec_name.startswith(fqdn):
                full_name = rec_name
                break

        if full_name and existing[full_name]["content"] == ip:
            unchanged += 1
            continue

        if full_name:
            # Update existing record
            rec_id = existing[full_name]["id"]
            result = _cf_request(
                "PUT",
                f"zones/{CLOUDFLARE_ZONE_ID}/dns_records/{rec_id}",
                {
                    "type": "A",
                    "name": fqdn,
                    "content": ip,
                    "ttl": CLOUDFLARE_TTL,
                },
            )
            if result:
                updated += 1
                logging.info("Tailscale DNS: updated %s -> %s", fqdn, ip)
            else:
                errors += 1
        else:
            # Create new record
            result = _cf_request(
                "POST",
                f"zones/{CLOUDFLARE_ZONE_ID}/dns_records",
                {
                    "type": "A",
                    "name": fqdn,
                    "content": ip,
                    "ttl": CLOUDFLARE_TTL,
                },
            )
            if result:
                created += 1
                logging.info("Tailscale DNS: created %s -> %s", fqdn, ip)
            else:
                errors += 1

    # Delete orphaned records (Tailscale IPs no longer in desired)
    for rec_name, rec in existing.items():
        fqdn_part = (
            rec_name.split(f".{TAILSCALE_DNS_SUBDOMAIN}")[0]
            if TAILSCALE_DNS_SUBDOMAIN
            else rec_name.split(".")[0]
        )
        if fqdn_part not in desired:
            _cf_request("DELETE", f"zones/{CLOUDFLARE_ZONE_ID}/dns_records/{rec['id']}")
            deleted += 1
            logging.info("Tailscale DNS: deleted %s -> %s", rec_name, rec["content"])

    return SyncResult(
        created=created,
        updated=updated,
        deleted=deleted,
        unchanged=unchanged,
        errors=errors,
        ok=errors == 0,
    )
