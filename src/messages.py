"""Notification message templates -- clear, actionable messages for humans.

Each function returns a tuple (message_text, level, context) ready for notify().
Messages explain WHAT happened, WHY, and WHAT TO DO if action is needed.
"""

from config import (
    USG_IP,
    CHECK_INTERVAL,
    REBOOT_SCORE_THRESHOLD,
    MAX_SCORE,
    POST_REBOOT_GRACE,
    REBOOT_COOLDOWN,
    MAX_REBOOTS_PER_DAY,
    INSTANCE_PRIORITY,
    PEER_IP,
    HTTP_PORT,
)
from notifier._types import Level, NotificationContext


def _dashboard_link() -> str:
    """Build a link to the local dashboard."""
    import socket
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "localhost"
    return f"http://{hostname}:{HTTP_PORT}/"


def _peer_label() -> str:
    if PEER_IP:
        return f"peer={PEER_IP}"
    return "standalone (pas de peer)"


# ===================================================================
# Startup / Shutdown
# ===================================================================


def startup() -> tuple[str, Level, NotificationContext | None]:
    lines = [
        "Le service de surveillance internet a demarre.",
        "",
        f"Machine : priority {INSTANCE_PRIORITY} ({_peer_label()})",
        f"Gateway USG : {USG_IP}",
        f"Check toutes les {CHECK_INTERVAL}s",
        f"Seuil reboot : score >= {REBOOT_SCORE_THRESHOLD}/{MAX_SCORE}",
        f"Max reboots/jour : {MAX_REBOOTS_PER_DAY}",
        "",
        f"Dashboard : {_dashboard_link()}",
    ]
    return "\n".join(lines), Level.INFO, None


def shutdown(reason: str = "arret manuel") -> tuple[str, Level, NotificationContext | None]:
    msg = (
        f"Le service de surveillance internet s'est arrete.\n"
        f"Raison : {reason}\n"
        f"\n"
        f"Le USG ne sera plus surveille jusqu'au prochain demarrage."
    )
    level = Level.CRITICAL if reason == "crash" else Level.INFO
    return msg, level, None


# ===================================================================
# Connectivity events
# ===================================================================


def reboot_launching(
    attempt: int,
    score: int,
    gateway_ok: bool,
    inet_count: int,
    inet_total: int,
    reboots_today: int,
    peer_info: dict,
    traceroute_summary: str = "",
) -> tuple[str, Level, NotificationContext]:
    lines = [
        f"Internet coupe -- redemarrage du routeur USG ({USG_IP}).",
        "",
        f"Tentative #{attempt} du jour ({reboots_today}/{MAX_REBOOTS_PER_DAY})",
        f"Score : {score}/{REBOOT_SCORE_THRESHOLD}",
        f"Gateway : {'OK' if gateway_ok else 'INJOIGNABLE'}",
        f"Internet : {inet_count}/{inet_total} cibles joignables",
    ]

    if peer_info.get("status") not in ("standalone", "unknown", ""):
        lines.append(
            f"Peer : {peer_info['status']} "
            f"(score={peer_info.get('score', '?')} "
            f"gw={peer_info.get('gateway', '?')} "
            f"inet={peer_info.get('internet', '?')})"
        )

    if traceroute_summary:
        lines.extend(["", f"Diagnostic : {traceroute_summary}"])

    lines.extend([
        "",
        f"Le routeur va redemarrer. Coupure reseau de ~2 min attendue.",
        f"Prochain check dans {POST_REBOOT_GRACE}s (grace post-reboot).",
    ])

    ctx = NotificationContext(
        score=score,
        threshold=REBOOT_SCORE_THRESHOLD,
        gateway_ok=gateway_ok,
        internet_ok_count=inet_count,
        internet_total=inet_total,
        reboot_count=attempt,
        reboots_today=reboots_today,
        max_reboots_per_day=MAX_REBOOTS_PER_DAY,
    )
    return "\n".join(lines), Level.CRITICAL, ctx


def recovery_with_reboot(
    duration: str,
    reboot_count: int,
    helped: bool,
) -> tuple[str, Level, NotificationContext]:
    verdict = "Le redemarrage a resolu le probleme." if helped else "Le probleme s'est resolu seul (le redemarrage n'a pas aide)."
    lines = [
        f"Connexion internet retablie apres {duration} de coupure.",
        "",
        f"Reboots tentes : {reboot_count}",
        verdict,
        "",
        "Tout fonctionne normalement.",
    ]
    ctx = NotificationContext(reboot_count=reboot_count, duration=duration)
    return "\n".join(lines), Level.INFO, ctx


def recovery_no_reboot(duration: str) -> tuple[str, Level, NotificationContext | None]:
    lines = [
        f"Connexion internet retablie apres {duration} de coupure.",
        "",
        "Aucun redemarrage n'a ete necessaire.",
        "La coupure etait probablement passagere.",
    ]
    return "\n".join(lines), Level.INFO, NotificationContext(duration=duration)


# ===================================================================
# ISP outage
# ===================================================================


def isp_outage_detected(
    duration: str,
    inet_total: int,
) -> tuple[str, Level, NotificationContext]:
    lines = [
        f"Probable panne chez le fournisseur internet.",
        "",
        f"Le routeur USG ({USG_IP}) repond normalement,",
        f"mais aucune des {inet_total} cibles internet n'est joignable",
        f"depuis {duration}.",
        "",
        "Les redemarrages automatiques sont suspendus",
        "(redemarrer le routeur ne resoudra pas une panne FAI).",
        "",
        "Verifier : status du FAI, incidents reseau, cablage fibre.",
    ]
    ctx = NotificationContext(
        gateway_ok=True,
        internet_ok_count=0,
        internet_total=inet_total,
        duration=duration,
    )
    return "\n".join(lines), Level.WARNING, ctx


# ===================================================================
# Circuit breaker
# ===================================================================


def max_reboots_reached(
    reboots_today: int,
) -> tuple[str, Level, NotificationContext]:
    lines = [
        f"Limite de {reboots_today} redemarrages/jour atteinte.",
        "",
        "Le watchdog passe en mode surveillance :",
        "il continue de surveiller et notifier,",
        "mais ne redemarrera plus le routeur aujourd'hui.",
        "",
        "Le compteur se reinitialisera demain a minuit.",
        "Si le probleme persiste, une intervention manuelle est necessaire.",
        "",
        f"Dashboard : {_dashboard_link()}",
    ]
    ctx = NotificationContext(
        reboots_today=reboots_today,
        max_reboots_per_day=MAX_REBOOTS_PER_DAY,
    )
    return "\n".join(lines), Level.CRITICAL, ctx


def ssh_failure(
    failure_count: int,
    retry_delay: str,
) -> tuple[str, Level, NotificationContext]:
    lines = [
        f"Impossible de se connecter au routeur USG ({USG_IP}) en SSH.",
        "",
        f"Echecs consecutifs : {failure_count}",
        f"Prochain essai dans : {retry_delay}",
        "",
        "Verifier :",
        f"  - Le routeur est-il accessible sur {USG_IP} ?",
        "  - Le service SSH est-il actif sur le USG ?",
        "  - Les cles SSH sont-elles valides ?",
        "",
        "Commande de test : sudo ./scripts/test.sh",
    ]
    ctx = NotificationContext(extra={"ssh_echecs": str(failure_count)})
    return "\n".join(lines), Level.WARNING, ctx


# ===================================================================
# Peer coordination
# ===================================================================


def divergence_detected(
    local_score: int,
    local_gw: bool,
    local_inet: int,
    peer_score: int,
    peer_gw: str,
    peer_inet: str,
) -> tuple[str, Level, NotificationContext | None]:
    if local_score > peer_score:
        diagnosis = (
            "Cette machine detecte un probleme que le peer ne voit pas.\n"
            "Cause probable : probleme reseau local sur cette machine,\n"
            "pas sur le routeur ou la ligne internet."
        )
    else:
        diagnosis = (
            "Le peer detecte un probleme que cette machine ne voit pas.\n"
            "Cause probable : probleme reseau local sur le peer."
        )

    lines = [
        "Les deux machines de surveillance ne voient pas la meme chose.",
        "",
        f"Cette machine : score={local_score} "
        f"gw={'OK' if local_gw else 'KO'} inet={local_inet}",
        f"Peer          : score={peer_score} "
        f"gw={peer_gw} inet={peer_inet}",
        "",
        diagnosis,
    ]
    return "\n".join(lines), Level.WARNING, None


# ===================================================================
# API commands
# ===================================================================


def api_pause() -> tuple[str, Level, NotificationContext | None]:
    return (
        "Mode surveillance active via l'API.\n"
        "Le watchdog ne redemarrera plus le routeur\n"
        "jusqu'a ce qu'il soit reactive (resume).",
        Level.WARNING,
        None,
    )


def api_resume() -> tuple[str, Level, NotificationContext | None]:
    return (
        "Mode surveillance desactive via l'API.\n"
        "Le watchdog peut a nouveau redemarrer le routeur si necessaire.",
        Level.INFO,
        None,
    )


def api_reboot() -> tuple[str, Level, NotificationContext | None]:
    return (
        f"Redemarrage manuel du routeur USG ({USG_IP}) demande via l'API.\n"
        "Coupure reseau de ~2 min attendue.",
        Level.CRITICAL,
        None,
    )


# ===================================================================
# Updates
# ===================================================================


def update_available(
    current: str,
    latest: str,
) -> tuple[str, Level, NotificationContext | None]:
    return (
        f"Mise a jour disponible : {current} -> {latest}\n"
        f"La mise a jour sera appliquee automatiquement apres validation.",
        Level.INFO,
        None,
    )


def update_success(
    old_version: str,
    new_version: str,
) -> tuple[str, Level, NotificationContext | None]:
    return (
        f"Mise a jour reussie : {old_version} -> {new_version}\n"
        "Le watchdog fonctionne normalement sur la nouvelle version.",
        Level.INFO,
        None,
    )


def update_failed(
    version: str,
    reason: str,
) -> tuple[str, Level, NotificationContext | None]:
    return (
        f"Mise a jour vers {version} echouee.\n"
        f"Raison : {reason}\n"
        "L'ancienne version a ete restauree automatiquement.",
        Level.WARNING,
        None,
    )


# ===================================================================
# DDNS Cloudflare
# ===================================================================


# ===================================================================
# Backup UniFi
# ===================================================================


def backup_ok(
    filename: str,
    size_mb: float,
    destination: str,
    source: str = "scheduled",
) -> tuple[str, Level, NotificationContext | None]:
    lines = [
        f"Backup UniFi config reussi.",
        "",
        f"Fichier : {filename} ({size_mb} MB)",
        f"Destination : {destination}",
        f"Declencheur : {source}",
    ]
    return "\n".join(lines), Level.INFO, None


def backup_failed(
    error: str,
    filename: str = "",
) -> tuple[str, Level, NotificationContext | None]:
    lines = [
        f"Echec du backup UniFi config.",
        "",
        f"Erreur : {error}",
    ]
    if filename:
        lines.append(f"Fichier : {filename}")
    lines.extend([
        "",
        "Verifier :",
        "  - rclone est installe et configure",
        "  - La destination remote est accessible",
        "  - Le repertoire de backup UniFi existe",
    ])
    return "\n".join(lines), Level.WARNING, None


def backup_stale(
    filename: str,
    age_hours: int,
    max_hours: int,
) -> tuple[str, Level, NotificationContext | None]:
    lines = [
        f"Le dernier backup UniFi date de {age_hours}h (max configure : {max_hours}h).",
        "",
        f"Fichier : {filename}",
        "",
        "L'auto-backup du UniFi Controller est peut-etre desactive ou en erreur.",
        "Verifier dans : UniFi Controller > Settings > System > Backups",
    ]
    return "\n".join(lines), Level.WARNING, None


# ===================================================================
# DDNS Cloudflare
# ===================================================================


def ddns_updated(
    previous_ip: str,
    current_ip: str,
    records_updated: int,
    record_names: str,
) -> tuple[str, Level, NotificationContext | None]:
    lines = [
        f"Adresse IP publique mise a jour.",
        "",
        f"Ancienne IP : {previous_ip}",
        f"Nouvelle IP : {current_ip}",
        f"Records DNS mis a jour : {records_updated} ({record_names})",
        "",
        "Les services exposes (VPN, acces distant, etc.) utilisent la nouvelle IP.",
    ]
    return "\n".join(lines), Level.INFO, None


def ddns_failed(
    current_ip: str,
    errors: list[str],
) -> tuple[str, Level, NotificationContext | None]:
    lines = [
        f"Echec de la mise a jour DNS Cloudflare.",
        "",
        f"IP publique detectee : {current_ip}",
        f"Erreurs :",
    ]
    for err in errors:
        lines.append(f"  - {err}")
    lines.extend([
        "",
        "Les records DNS pointent encore vers l'ancienne IP.",
        "Verifier le token Cloudflare et les records dans le dashboard Cloudflare.",
    ])
    return "\n".join(lines), Level.WARNING, None
