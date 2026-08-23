"""Verification des pages statut FAI pour correler avec les pannes detectees.

Scrape les pages de statut des principaux FAI francais (Free, Orange, SFR, Bouygues)
pour detecter les incidents declares et eviter les reboots USG inutiles.
"""

import json
import logging
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

import config


# ---------------------------------------------------------------------------
# Configuration FAI par defaut
# ---------------------------------------------------------------------------

ISP_CONFIGS: dict[str, dict[str, str | list[str]]] = {
    "Free": {
        "url": "https://free.fr/freebox/informations",
        "keywords": ["incident", "perturbation", "panne", "interruption"],
    },
    "Orange": {
        "url": "https://assistance.orange.fr",
        "keywords": [
            "incident en cours",
            "perturbation",
            "panne",
            "interruption de service",
        ],
    },
    "SFR": {
        "url": "https://assistance.sfr.fr",
        "keywords": ["incident", "perturbation", "panne", "interruption"],
    },
    "Bouygues": {
        "url": "https://www.assistance.bouyguestelecom.fr",
        "keywords": ["incident", "panne", "perturbation", "interruption"],
    },
}

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "vigil/1.0"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IspStatus:
    """Resultat de verification pour un FAI."""

    name: str
    url: str
    has_incident: bool
    keywords_found: list[str]
    error: str | None
    checked_at: str


@dataclass(frozen=True)
class IspCheckResult:
    """Resultat global de la verification de tous les FAI configures."""

    statuses: list[IspStatus]
    any_incident: bool
    summary: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def is_configured() -> bool:
    """Retourne True si la verification des statuts FAI est activee."""
    return config.ISP_STATUS_ENABLED


def _get_effective_urls() -> dict[str, str]:
    """Retourne les URLs effectives (defaut + surcharges via ISP_STATUS_URLS)."""
    overrides: dict[str, str] = {}
    if config.ISP_STATUS_URLS:
        try:
            parsed = json.loads(config.ISP_STATUS_URLS)
            if isinstance(parsed, dict):
                overrides = {str(k): str(v) for k, v in parsed.items()}
            else:
                logging.warning(
                    "ISP_STATUS_URLS invalide -- doit etre un objet JSON {FAI: url}"
                )
        except json.JSONDecodeError as e:
            logging.warning("ISP_STATUS_URLS: JSON invalide -- %s", e)

    urls: dict[str, str] = {}
    for isp_name, cfg in ISP_CONFIGS.items():
        urls[isp_name] = overrides.get(isp_name, str(cfg["url"]))
    return urls


# ---------------------------------------------------------------------------
# Verification unitaire
# ---------------------------------------------------------------------------


def _check_single_isp(name: str, url: str, keywords: list[str]) -> IspStatus:
    """Verifie la page statut d'un FAI. Ne leve jamais d'exception."""
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=config.ISP_STATUS_TIMEOUT) as response:
            raw = response.read(256 * 1024)  # max 256 KB
            try:
                content = raw.decode("utf-8", errors="replace").lower()
            except Exception:
                content = ""

        found = [kw for kw in keywords if kw.lower() in content]
        has_incident = len(found) > 0

        if has_incident:
            logging.info(
                "Statut FAI %s : incident potentiel detecte (mots-cles: %s)",
                name,
                ", ".join(found),
            )
        else:
            logging.debug("Statut FAI %s : aucun incident detecte", name)

        return IspStatus(
            name=name,
            url=url,
            has_incident=has_incident,
            keywords_found=found,
            error=None,
            checked_at=checked_at,
        )

    except urllib.error.HTTPError as e:
        logging.debug("Statut FAI %s : erreur HTTP %d", name, e.code)
        return IspStatus(
            name=name,
            url=url,
            has_incident=False,
            keywords_found=[],
            error=f"HTTP {e.code}",
            checked_at=checked_at,
        )
    except urllib.error.URLError as e:
        logging.debug("Statut FAI %s : erreur reseau -- %s", name, e.reason)
        return IspStatus(
            name=name,
            url=url,
            has_incident=False,
            keywords_found=[],
            error=f"Reseau: {e.reason}",
            checked_at=checked_at,
        )
    except Exception as e:
        logging.debug("Statut FAI %s : erreur inattendue -- %s", name, e)
        return IspStatus(
            name=name,
            url=url,
            has_incident=False,
            keywords_found=[],
            error=str(e),
            checked_at=checked_at,
        )


# ---------------------------------------------------------------------------
# Verification parallele de tous les FAI
# ---------------------------------------------------------------------------


def check_isp_status() -> IspCheckResult:
    """Verifie toutes les pages statut FAI en parallele.

    Retourne un IspCheckResult avec les resultats partiels meme en cas
    d'erreurs individuelles. Ne leve jamais d'exception.
    """
    effective_urls = _get_effective_urls()
    statuses: list[IspStatus] = []

    with ThreadPoolExecutor(
        max_workers=len(ISP_CONFIGS), thread_name_prefix="isp-check"
    ) as executor:
        futures = {
            executor.submit(
                _check_single_isp,
                name,
                effective_urls[name],
                list(ISP_CONFIGS[name]["keywords"]),  # type: ignore[arg-type]
            ): name
            for name in ISP_CONFIGS
        }
        for future in as_completed(futures):
            try:
                statuses.append(future.result())
            except Exception as e:
                isp_name = futures[future]
                logging.debug("Statut FAI %s : exception future -- %s", isp_name, e)
                statuses.append(
                    IspStatus(
                        name=isp_name,
                        url=effective_urls.get(isp_name, ""),
                        has_incident=False,
                        keywords_found=[],
                        error=str(e),
                        checked_at=datetime.now(timezone.utc).isoformat(),
                    )
                )

    any_incident = any(s.has_incident for s in statuses)

    if any_incident:
        incident_names = [s.name for s in statuses if s.has_incident]
        summary = f"Incident signale par : {', '.join(incident_names)}"
    else:
        reachable = [s.name for s in statuses if s.error is None]
        if reachable:
            summary = f"Aucun incident detecte ({', '.join(reachable)} verifies)"
        else:
            summary = "Toutes les pages FAI inaccessibles (erreur reseau probable)"

    return IspCheckResult(
        statuses=statuses,
        any_incident=any_incident,
        summary=summary,
    )
