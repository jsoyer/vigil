"""Ntfy notification channel -- supports cloud and self-hosted instances.

Canal enrichi (v2.2.0) : priorites 1-5 par niveau, titre + tags par instance
et par site, Click vers le dashboard de l'instance emettrice, Markdown
degradable, troncature a 4096 octets, authentification par NTFY_TOKEN, et
routage de topic par categorie (alertes de ligne -> NTFY_TOPIC, cycle de
vie/rapports -> NTFY_TOPIC_OPS).
"""

import logging
import urllib.error
import urllib.request

from config import (
    HTTP_PORT,
    INSTANCE_ID,
    NTFY_TIMEOUT,
    NTFY_TOKEN,
    NTFY_TOPIC,
    NTFY_TOPIC_OPS,
    NTFY_URL,
)
from notifier._types import Level, NotificationContext, format_context_inline

_LEVEL_PRIORITY: dict[Level, int] = {
    Level.INFO: 3,  # default
    Level.WARNING: 4,  # high
    Level.CRITICAL: 5,  # urgent
}

_LEVEL_TAGS: dict[Level, str] = {
    Level.INFO: "information_source",
    Level.WARNING: "warning",
    Level.CRITICAL: "rotating_light",
}

# Priorite ntfy pour les notifications de fond (rapports quotidiens/
# hebdomadaires et evenements de cycle de vie a niveau INFO) : "low", elle
# ne doit pas faire vibrer un telephone a 8h du matin. Ne s'applique qu'aux
# messages INFO -- une alerte "ops" en WARNING/CRITICAL (ex: sauvegarde en
# echec) garde sa priorite normale, cf. test_ops_warning_keeps_level_priority.
_OPS_INFO_PRIORITY = 2

# Limite dure du corps d'un message ntfy.sh, respectee aussi en self-hosted
# par coherence (cf. PRD Ntfy-first S3.4).
_MAX_BODY_BYTES = 4096
_TRUNCATION_SUFFIX = "\n... [tronque, voir Click]"

# Aucune derivation de "site" (dijon/nice) n'existe ailleurs dans le projet
# (verifie dans mqtt_publisher.py -- INSTANCE_ID y est utilise tel quel).
# On cherche une sous-chaine connue plutot que de supposer un format
# positionnel fixe (ex: "premier token avant '_'"), pour rester robuste aux
# variantes de nommage des 4 instances de production.
_KNOWN_SITES = ("dijon", "nice")

# Longueur max du "resume court" de Title, pour rester lisible sur un ecran
# verrouille.
_TITLE_SUMMARY_MAX_CHARS = 100


def is_configured() -> bool:
    return bool(NTFY_URL and NTFY_TOPIC)


def _derive_site(instance_id: str) -> str:
    """Deduit le site (dijon/nice) a partir de l'INSTANCE_ID normalise."""
    for site in _KNOWN_SITES:
        if site in instance_id:
            return site
    return instance_id


def _priority_for(level: Level, category: str) -> int:
    if category == "ops" and level == Level.INFO:
        return _OPS_INFO_PRIORITY
    return _LEVEL_PRIORITY.get(level, 3)


def _ascii_safe(value: str) -> str:
    """Neutralise tout caractere hors ASCII pour un usage sur en-tete HTTP."""
    return value.encode("ascii", errors="replace").decode("ascii")


def _short_summary(message: str) -> str:
    first_line = message.splitlines()[0] if message else ""
    if len(first_line) > _TITLE_SUMMARY_MAX_CHARS:
        first_line = first_line[: _TITLE_SUMMARY_MAX_CHARS - 3] + "..."
    return first_line


def _truncate_body(body: str) -> str:
    """Tronque proprement un corps de message a _MAX_BODY_BYTES octets.

    Ne coupe jamais au milieu d'un caractere UTF-8 multi-octets.
    """
    body_bytes = body.encode("utf-8")
    if len(body_bytes) <= _MAX_BODY_BYTES:
        return body

    suffix_bytes = _TRUNCATION_SUFFIX.encode("utf-8")
    limit = max(_MAX_BODY_BYTES - len(suffix_bytes), 0)
    truncated = body_bytes[:limit]
    while truncated:
        try:
            text = truncated.decode("utf-8")
            break
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    else:
        text = ""
    return text + _TRUNCATION_SUFFIX


def send(
    message: str,
    level: Level,
    context: NotificationContext | None,
    hostname: str,
    timestamp: str,
) -> bool:
    """Send a Ntfy notification. Never raises."""
    category = context.category if context is not None else "alert"
    topic = NTFY_TOPIC_OPS if category == "ops" else NTFY_TOPIC
    url = f"{NTFY_URL.rstrip('/')}/{topic}"

    body = f"{message}\n\n{hostname} -- {timestamp}"
    if context is not None:
        ctx_str = format_context_inline(context)
        if ctx_str:
            body += f"\n{ctx_str}"
    body = _truncate_body(body)

    site = _derive_site(INSTANCE_ID)
    title = _ascii_safe(f"Vigil {INSTANCE_ID} - {_short_summary(message)}")
    tags = _ascii_safe(f"{_LEVEL_TAGS.get(level, '')},{INSTANCE_ID},{site}")

    headers = {
        "Title": title,
        "Priority": str(_priority_for(level, category)),
        "Tags": tags,
        "Markdown": "yes",
        "Click": f"http://{hostname}:{HTTP_PORT}/dashboard",
        "Content-Type": "text/plain; charset=utf-8",
    }
    if NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {NTFY_TOKEN}"

    try:
        data = body.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=NTFY_TIMEOUT) as resp:
            status = resp.status
        if status == 200:
            logging.debug("Ntfy: notification envoyee")
            return True
        logging.warning("Ntfy: HTTP %d", status)
        return False
    except urllib.error.HTTPError as e:
        logging.warning("Ntfy: HTTP %d", e.code)
    except urllib.error.URLError as e:
        if "timed out" in str(e.reason).lower():
            logging.warning("Ntfy: timeout")
        else:
            logging.warning("Ntfy: erreur reseau")
    except Exception as e:
        logging.warning("Ntfy: erreur -- %s", e)
    return False
