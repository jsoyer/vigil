#!/usr/bin/env python3
"""
USG Watchdog -- Surveillance de connexion fibre + reboot automatique USG Ubiquiti

Systeme de scoring avec circuit breaker :
- Scoring : penalites par cycle (gateway KO, internet KO), recuperation si OK
- Backoff exponentiel : cooldown double a chaque reboot sans recuperation
- Max reboots/jour : passe en mode surveillance apres le cap
- Backoff SSH : ralentit les tentatives SSH en cas d'echec repete
- Detection ISP : identifie "gateway OK + internet KO" prolonge comme panne ISP
- Synthese au retablissement : resume de la coupure envoyee par Telegram
"""

import time
import logging
import logging.handlers
import sys
from datetime import datetime

from config import (
    CHECK_INTERVAL,
    REBOOT_SCORE_THRESHOLD,
    MAX_SCORE,
    SCORE_GATEWAY_DOWN,
    SCORE_INTERNET_ALL_DOWN,
    SCORE_INTERNET_PARTIAL,
    SCORE_DECAY_OK,
    SCORE_DECAY_PARTIAL,
    POST_REBOOT_GRACE,
    REBOOT_COOLDOWN,
    MAX_REBOOT_COOLDOWN,
    MAX_REBOOTS_PER_DAY,
    SSH_FAILURE_BACKOFF_START,
    SSH_FAILURE_COOLDOWN,
    MAX_SSH_COOLDOWN,
    ISP_OUTAGE_DETECTION_DELAY,
    USG_REBOOT_WAIT,
    INSTANCE_PRIORITY,
    PEER_IP,
    HTTP_PORT,
    DAILY_REPORT_HOUR,
    WEEKLY_REPORT_DAY,
    UNIFI_BACKUP_SCHEDULE_HOUR,
    LOG_FILE,
    LOG_LEVEL,
)
from connectivity import check_connectivity
from usg import reboot_usg
from notifier import notify, Level, NotificationContext
from state import WatchdogState, StateHolder, CMD_PAUSE, CMD_RESUME, CMD_REBOOT
from http_server import start_http_server
from peer import should_reboot as peer_should_reboot, get_peer_info, check_divergence
from report import generate_daily_report, format_report_notification, generate_weekly_report, format_weekly_report
from diagnostics import run_traceroute
from connectivity import gateway_latency, internet_latency
from ddns_cloudflare import check_and_update as ddns_check, is_configured as ddns_configured
from backup_unifi import run_backup as unifi_backup, is_configured as backup_configured
from mqtt_publisher import MqttPublisher
from snmp_monitor import read_usg_metrics, UsgMetrics
from speedtest import run_speedtest, SPEEDTEST_INTERVAL_CYCLES
from history import HistoryBuffer
import messages as msg
from events import EventLog, STARTUP, SHUTDOWN, REBOOT, REBOOT_FAILED, RECOVERY
from events import ISP_OUTAGE, ISP_RECOVERY, PEER_STANDDOWN, SSH_BACKOFF, MAX_REBOOTS


def setup_logging() -> None:
    """Configure le logging vers fichier + console avec rotation."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger.setLevel(level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except PermissionError:
        root_logger.warning(
            "Impossible d'ecrire dans %s -- logs console uniquement", LOG_FILE
        )


def clamp(value: int, min_value: int, max_value: int) -> int:
    """Borne une valeur entre min et max."""
    return max(min_value, min(value, max_value))


def compute_cycle_delta(gateway_ok: bool, internet_ok_count: int) -> int:
    """
    Calcule le delta de score pour un cycle de verification.

    Penalites :
      gateway KO          -> +SCORE_GATEWAY_DOWN
      internet 0/N        -> +SCORE_INTERNET_ALL_DOWN
      internet 1/N        -> +SCORE_INTERNET_PARTIAL
      internet >= 2/N     -> +0

    Recuperation :
      gateway OK + internet >= 2  -> -SCORE_DECAY_OK
      gateway OK + internet == 1  -> -SCORE_DECAY_PARTIAL
    """
    delta = 0

    if not gateway_ok:
        delta += SCORE_GATEWAY_DOWN

    if internet_ok_count == 0:
        delta += SCORE_INTERNET_ALL_DOWN
    elif internet_ok_count == 1:
        delta += SCORE_INTERNET_PARTIAL

    if gateway_ok and internet_ok_count >= 2:
        delta -= SCORE_DECAY_OK
    elif gateway_ok and internet_ok_count == 1:
        delta -= SCORE_DECAY_PARTIAL

    return delta


def compute_effective_cooldown(consecutive_reboots: int) -> int:
    """
    Cooldown exponentiel : double a chaque reboot sans recuperation.
    Reboot 1: REBOOT_COOLDOWN (15 min)
    Reboot 2: x2 (30 min)
    Reboot 3: x4 (1h)
    Reboot 4: x8 (2h)
    Reboot 5+: cap a MAX_REBOOT_COOLDOWN (4h)
    """
    exponent = min(consecutive_reboots, 5)
    cooldown = REBOOT_COOLDOWN * (2 ** exponent)
    return min(cooldown, MAX_REBOOT_COOLDOWN)


def compute_ssh_retry_delay(consecutive_ssh_failures: int) -> int:
    """
    Delai avant de retenter SSH apres echecs consecutifs.
    < SSH_FAILURE_BACKOFF_START echecs : pas de delai
    Ensuite : SSH_FAILURE_COOLDOWN double a chaque palier, cap MAX_SSH_COOLDOWN.
    """
    if consecutive_ssh_failures < SSH_FAILURE_BACKOFF_START:
        return 0
    exponent = (consecutive_ssh_failures - SSH_FAILURE_BACKOFF_START) // 3
    delay = SSH_FAILURE_COOLDOWN * (2 ** min(exponent, 4))
    return min(delay, MAX_SSH_COOLDOWN)


def _format_duration(seconds: int) -> str:
    """Formate une duree en texte lisible."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}min"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if minutes:
        return f"{hours}h{minutes:02d}"
    return f"{hours}h"


def main() -> None:
    setup_logging()

    # Scoring state
    failure_score = 0
    was_degraded = False

    # Reboot state
    last_reboot_time = 0.0
    grace_until = 0.0
    consecutive_reboots = 0
    reboots_today = 0
    today_date = datetime.now().date()
    surveillance_only = False

    # SSH backoff state
    consecutive_ssh_failures = 0
    last_ssh_attempt_time = 0.0

    # ISP outage detection
    isp_pattern_start = 0.0  # timestamp when "gw OK + inet KO" pattern started
    isp_outage_detected = False

    # Outage tracking for summary
    outage_start_time = 0.0
    outage_reboot_count = 0
    outage_reboot_helped = False

    # Coordination
    threshold_reached_time = 0.0
    start_time = time.time()
    peer_info: dict[str, str | int] = {"status": "unknown", "score": 0, "gateway": "", "internet": ""}
    divergence_notified = False
    last_report_date = datetime.now().date()
    last_weekly_report_week = datetime.now().isocalendar()[1]
    maintenance_until = 0.0
    last_backup_date = datetime.now().date()

    # Version (read from VERSION file)
    _version = "0.0.0"
    for vpath in ("VERSION", "../VERSION", "../../VERSION"):
        try:
            _version = open(vpath).read().strip()
            break
        except FileNotFoundError:
            continue

    # Event history + HTTP state server
    global _event_log
    event_log = EventLog()
    _event_log = event_log
    state_holder = StateHolder()
    history_buffer = HistoryBuffer()
    start_http_server(state_holder, HTTP_PORT, event_log, history_buffer)

    # MQTT publisher (optional)
    mqtt = MqttPublisher(state_holder)
    mqtt.start()

    # Cycle counters for periodic tasks
    cycle_count = 0

    logging.info("=" * 60)
    logging.info("USG Watchdog demarre")
    logging.info("   Instance : priority=%d", INSTANCE_PRIORITY)
    if PEER_IP:
        logging.info("   Peer : %s:%d", PEER_IP, HTTP_PORT)
    else:
        logging.info("   Mode : standalone (pas de peer)")
    logging.info("   Check toutes les %ds", CHECK_INTERVAL)
    logging.info(
        "   Seuil de reboot : score >= %d (max %d)",
        REBOOT_SCORE_THRESHOLD, MAX_SCORE,
    )
    logging.info("   Grace post-reboot : %ds", POST_REBOOT_GRACE)
    logging.info(
        "   Cooldown : %ds (backoff jusqu'a %ds)",
        REBOOT_COOLDOWN, MAX_REBOOT_COOLDOWN,
    )
    logging.info("   Max reboots/jour : %d", MAX_REBOOTS_PER_DAY)
    logging.info("   HTTP state : port %d", HTTP_PORT)
    logging.info("=" * 60)

    peer_info_str = f"peer={PEER_IP}" if PEER_IP else "standalone"
    text, level, ctx = msg.startup()
    notify(text, level, ctx)
    event_log.record(STARTUP, priority=INSTANCE_PRIORITY, peer=peer_info_str)

    while True:
        now = time.time()

        # Reset daily reboot counter at midnight
        current_date = datetime.now().date()
        if current_date != today_date:
            if reboots_today > 0:
                logging.info(
                    "Nouveau jour -- reset compteur reboots (hier: %d)", reboots_today
                )
            reboots_today = 0
            today_date = current_date
            if surveillance_only:
                surveillance_only = False
                logging.info("Mode surveillance desactive -- reboots autorises")

        # --- Daily report ---
        if (
            DAILY_REPORT_HOUR >= 0
            and current_date != last_report_date
            and datetime.now().hour >= DAILY_REPORT_HOUR
        ):
            last_report_date = current_date
            try:
                report = generate_daily_report(
                    event_log,
                    report_date=current_date if current_date != today_date else None,
                    uptime_seconds=now - start_time,
                    current_score=failure_score,
                    peer_status=str(peer_info.get("status", "unknown")),
                )
                report_text = format_report_notification(report)
                logging.info("Rapport quotidien envoye")
                notify(report_text, Level.INFO)
                event_log.record("daily_report")
            except Exception as e:
                logging.warning("Erreur generation rapport quotidien : %s", e)

        # --- Weekly report ---
        current_week = datetime.now().isocalendar()[1]
        if (
            WEEKLY_REPORT_DAY >= 0
            and current_week != last_weekly_report_week
            and datetime.now().weekday() == WEEKLY_REPORT_DAY
            and datetime.now().hour >= DAILY_REPORT_HOUR
        ):
            last_weekly_report_week = current_week
            try:
                wreport = generate_weekly_report(
                    event_log,
                    uptime_seconds=now - start_time,
                    current_score=failure_score,
                    peer_status=str(peer_info.get("status", "unknown")),
                )
                wreport_text = format_weekly_report(wreport)
                logging.info("Rapport hebdomadaire envoye")
                notify(wreport_text, Level.INFO)
                event_log.record("weekly_report")
            except Exception as e:
                logging.warning("Erreur generation rapport hebdomadaire : %s", e)

        # --- Scheduled UniFi backup ---
        if (
            backup_configured()
            and UNIFI_BACKUP_SCHEDULE_HOUR >= 0
            and current_date != last_backup_date
            and datetime.now().hour >= UNIFI_BACKUP_SCHEDULE_HOUR
        ):
            last_backup_date = current_date
            try:
                bresult = unifi_backup(source="scheduled")
                if bresult.ok:
                    text_b, level_b, ctx_b = msg.backup_ok(
                        bresult.filename, bresult.to_dict()["size_mb"],
                        bresult.destination, "quotidien",
                    )
                else:
                    text_b, level_b, ctx_b = msg.backup_failed(bresult.error, bresult.filename)
                notify(text_b, level_b, ctx_b)
                event_log.record(
                    "backup_ok" if bresult.ok else "backup_failed",
                    filename=bresult.filename, size=bresult.size_bytes,
                )
                if bresult.stale:
                    text_s, level_s, ctx_s = msg.backup_stale(
                        bresult.filename, bresult.stale_hours,
                        __import__("config").UNIFI_BACKUP_MAX_AGE_HOURS,
                    )
                    notify(text_s, level_s, ctx_s)
                    event_log.record("backup_stale", age_hours=bresult.stale_hours)
            except Exception as e:
                logging.warning("Erreur backup UniFi : %s", e)

        # --- Process pending commands from HTTP API ---
        cmd = state_holder.poll_command()
        if cmd == CMD_PAUSE:
            if not surveillance_only:
                surveillance_only = True
                logging.info("Mode surveillance active via API")
                text, level, ctx = msg.api_pause()
                notify(text, level, ctx)
                event_log.record("api_pause")
        elif cmd == CMD_RESUME:
            if surveillance_only:
                surveillance_only = False
                logging.info("Mode surveillance desactive via API")
                text, level, ctx = msg.api_resume()
                notify(text, level, ctx)
                event_log.record("api_resume")
        elif cmd == CMD_REBOOT:
            logging.warning("Reboot manuel demande via API")
            text, level, ctx = msg.api_reboot()
            notify(text, level, ctx)
            event_log.record("api_reboot")
            success = reboot_usg()
            if success:
                last_reboot_time = time.time()
                grace_until = last_reboot_time + POST_REBOOT_GRACE
                failure_score = 0
                consecutive_reboots += 1
                reboots_today += 1
                outage_reboot_count += 1
                event_log.record(REBOOT, attempt=consecutive_reboots, source="api")
                logging.info("Reboot USG envoye via API -- Grace %ds", POST_REBOOT_GRACE)
                for _ in range(USG_REBOOT_WAIT):
                    time.sleep(1)
            else:
                logging.error("Reboot manuel echoue")
                event_log.record(REBOOT_FAILED, source="api")
        elif cmd and cmd.startswith("maintenance:"):
            try:
                duration_min = int(cmd.split(":")[1])
                maintenance_until = now + (duration_min * 60)
                surveillance_only = True
                logging.info(
                    "Mode maintenance active pour %d min via API", duration_min
                )
                notify(
                    f"Mode maintenance active pour {duration_min} minutes.\n"
                    f"Le watchdog ne redemarrera pas le routeur pendant cette periode.",
                    Level.WARNING,
                )
                event_log.record("maintenance_start", duration_min=duration_min)
            except (ValueError, IndexError):
                logging.warning("Commande maintenance invalide: %s", cmd)

        # Check maintenance window expiration
        if surveillance_only and maintenance_until > 0 and now >= maintenance_until:
            surveillance_only = False
            maintenance_until = 0.0
            logging.info("Mode maintenance termine")
            notify("Mode maintenance termine. Surveillance normale reprise.")
            event_log.record("maintenance_end")

        # Grace post-reboot : on ignore les echecs
        if now < grace_until:
            remaining = int(grace_until - now)
            logging.debug("Grace post-reboot -- %ds restants", remaining)
            time.sleep(CHECK_INTERVAL)
            continue

        result = check_connectivity()
        delta = compute_cycle_delta(result.gateway_ok, result.internet_ok_count)
        failure_score = clamp(failure_score + delta, 0, MAX_SCORE)

        # --- ISP outage pattern detection ---
        is_isp_pattern = result.gateway_ok and result.internet_ok_count == 0
        if is_isp_pattern:
            if isp_pattern_start == 0.0:
                isp_pattern_start = now
            elif not isp_outage_detected:
                elapsed = now - isp_pattern_start
                if elapsed >= ISP_OUTAGE_DETECTION_DELAY:
                    isp_outage_detected = True
                    event_log.record(ISP_OUTAGE, duration=_format_duration(int(elapsed)))
                    logging.warning(
                        "Probable panne ISP detectee (gw OK + inet KO depuis %s)",
                        _format_duration(int(elapsed)),
                    )
                    text, level, ctx = msg.isp_outage_detected(
                        _format_duration(int(elapsed)), result.internet_total,
                    )
                    notify(text, level, ctx)
        else:
            if isp_outage_detected and result.internet_ok_count >= 2:
                isp_outage_detected = False
                event_log.record(ISP_RECOVERY)
                logging.info("Pattern ISP termine -- retour a la normale")
            if not is_isp_pattern:
                isp_pattern_start = 0.0

        # --- Logging ---
        if delta > 0:
            logging.warning(
                "gw=%s internet=%d/%d delta=%+d score=%d/%d%s",
                "OK" if result.gateway_ok else "KO",
                result.internet_ok_count,
                result.internet_total,
                delta,
                failure_score,
                REBOOT_SCORE_THRESHOLD,
                " [ISP?]" if isp_outage_detected else "",
            )
        elif delta < 0:
            logging.info(
                "gw=%s internet=%d/%d delta=%+d score=%d/%d",
                "OK" if result.gateway_ok else "KO",
                result.internet_ok_count,
                result.internet_total,
                delta,
                failure_score,
                REBOOT_SCORE_THRESHOLD,
            )
        else:
            logging.debug(
                "gw=%s internet=%d/%d delta=%+d score=%d/%d",
                "OK" if result.gateway_ok else "KO",
                result.internet_ok_count,
                result.internet_total,
                delta,
                failure_score,
                REBOOT_SCORE_THRESHOLD,
            )

        # --- Peer status + divergence detection ---
        peer_info = get_peer_info()

        if failure_score > 0 or (peer_info["status"] not in ("standalone", "unreachable", "unknown") and peer_info["score"] > 0):
            divergence_raw = check_divergence(
                failure_score, result.gateway_ok, result.internet_ok_count,
            )
            if divergence_raw and not divergence_notified:
                divergence_notified = True
                logging.warning("Divergence peer detectee")
                text, level, ctx = msg.divergence_detected(
                    failure_score, result.gateway_ok, result.internet_ok_count,
                    int(peer_info.get("score", 0)),
                    str(peer_info.get("gateway", "?")),
                    str(peer_info.get("internet", "?")),
                )
                notify(text, level, ctx)
                event_log.record("divergence", local_score=failure_score, peer_score=peer_info["score"])
        else:
            divergence_notified = False

        # Track if reboot helped: score back to 0 after at least one reboot
        if failure_score == 0 and outage_reboot_count > 0 and not outage_reboot_helped:
            outage_reboot_helped = True

        # --- Recovery detection ---
        if was_degraded and failure_score == 0:
            duration_str = ""
            if outage_start_time > 0:
                outage_duration = int(now - outage_start_time)
                duration_str = f" apres {_format_duration(outage_duration)}"

            dur = _format_duration(int(now - outage_start_time)) if outage_start_time > 0 else "?"

            if outage_reboot_count > 0:
                text, level, ctx = msg.recovery_with_reboot(
                    dur, outage_reboot_count, outage_reboot_helped,
                )
            else:
                text, level, ctx = msg.recovery_no_reboot(dur)

            logging.info("Connexion retablie apres %s", dur)
            event_log.record(
                RECOVERY,
                reboots=outage_reboot_count,
                helped=outage_reboot_helped,
                duration=dur,
            )
            notify(text, level, ctx)

            was_degraded = False
            outage_start_time = 0.0
            outage_reboot_count = 0
            outage_reboot_helped = False
            consecutive_reboots = 0
            consecutive_ssh_failures = 0

            # DDNS check on recovery (IP may have changed after reboot)
            if ddns_configured():
                ddns_result = ddns_check(force=True)
                if ddns_result and ddns_result.changed:
                    if ddns_result.records_failed == 0:
                        text_d, level_d, ctx_d = msg.ddns_updated(
                            ddns_result.previous_ip, ddns_result.current_ip,
                            ddns_result.records_updated,
                            ", ".join(r.strip() for r in __import__("config").CLOUDFLARE_RECORD_NAMES.split(",")),
                        )
                    else:
                        text_d, level_d, ctx_d = msg.ddns_failed(
                            ddns_result.current_ip, list(ddns_result.errors),
                        )
                    notify(text_d, level_d, ctx_d)
                    event_log.record(
                        "dns_updated" if ddns_result.records_failed == 0 else "dns_update_failed",
                        old_ip=ddns_result.previous_ip,
                        new_ip=ddns_result.current_ip,
                        records=ddns_result.records_updated,
                    )

        if failure_score > 0 and not was_degraded:
            was_degraded = True
            outage_start_time = now

        # Track when threshold is first reached (for secondary takeover delay)
        if failure_score >= REBOOT_SCORE_THRESHOLD and threshold_reached_time == 0.0:
            threshold_reached_time = now
            # Run traceroute on first threshold hit to diagnose the break
            logging.info("Lancement du traceroute diagnostique...")
            traceroute_result = run_traceroute()
            if traceroute_result:
                logging.info("Traceroute: %s", traceroute_result.summary())
                event_log.record(
                    "traceroute",
                    target=traceroute_result.target,
                    break_point=traceroute_result.break_point,
                    last_hop=traceroute_result.last_responsive_hop,
                    reached=traceroute_result.reached_target,
                )
        elif failure_score < REBOOT_SCORE_THRESHOLD:
            threshold_reached_time = 0.0

        # --- Reboot decision ---
        if failure_score >= REBOOT_SCORE_THRESHOLD:
            # Check surveillance-only mode (max reboots/day)
            if surveillance_only:
                logging.info(
                    "Seuil atteint (score=%d) mais mode surveillance "
                    "(max %d reboots/jour depasse)",
                    failure_score,
                    MAX_REBOOTS_PER_DAY,
                )
                time.sleep(CHECK_INTERVAL)
                continue

            # Check cooldown with exponential backoff
            effective_cooldown = compute_effective_cooldown(consecutive_reboots)
            elapsed_since_reboot = now - last_reboot_time

            if last_reboot_time > 0 and elapsed_since_reboot < effective_cooldown:
                remaining = int(effective_cooldown - elapsed_since_reboot)
                logging.info(
                    "Seuil atteint (score=%d) mais cooldown actif "
                    "(%s, tentative #%d) -- %ds restants",
                    failure_score,
                    _format_duration(effective_cooldown),
                    consecutive_reboots + 1,
                    remaining,
                )
                time.sleep(CHECK_INTERVAL)
                continue

            # Check SSH backoff
            ssh_retry_delay = compute_ssh_retry_delay(consecutive_ssh_failures)
            if ssh_retry_delay > 0:
                elapsed_since_ssh = now - last_ssh_attempt_time
                if elapsed_since_ssh < ssh_retry_delay:
                    remaining = int(ssh_retry_delay - elapsed_since_ssh)
                    logging.info(
                        "SSH backoff actif (%d echecs) -- retry dans %ds",
                        consecutive_ssh_failures,
                        remaining,
                    )
                    time.sleep(CHECK_INTERVAL)
                    continue

            # ISP outage: skip reboot if pattern detected
            if isp_outage_detected:
                logging.info(
                    "Seuil atteint (score=%d) mais panne ISP probable "
                    "-- reboot USG inutile",
                    failure_score,
                )
                time.sleep(CHECK_INTERVAL)
                continue

            # Peer coordination check
            current_state = WatchdogState(
                failure_score=failure_score,
                threshold=REBOOT_SCORE_THRESHOLD,
                was_degraded=was_degraded,
                last_reboot_time=last_reboot_time,
                grace_until=grace_until,
                consecutive_reboots=consecutive_reboots,
                reboots_today=reboots_today,
                surveillance_only=surveillance_only,
                consecutive_ssh_failures=consecutive_ssh_failures,
                last_ssh_attempt_time=last_ssh_attempt_time,
                isp_outage_detected=isp_outage_detected,
                outage_start_time=outage_start_time,
                outage_reboot_count=outage_reboot_count,
                outage_reboot_helped=outage_reboot_helped,
                threshold_reached_time=threshold_reached_time,
                instance_priority=INSTANCE_PRIORITY,
                gateway_ok=result.gateway_ok,
                internet_ok_count=result.internet_ok_count,
                internet_total=result.internet_total,
                gateway_rtt_ms=result.gateway_rtt_ms,
                internet_avg_rtt_ms=result.internet_avg_rtt_ms,
                latency_degraded=internet_latency.is_degraded(),
                version=_version,
                timestamp=datetime.now().isoformat(),
                uptime_seconds=now - start_time,
            )
            state_holder.state = current_state

            proceed, reason = peer_should_reboot(current_state, result.gateway_ok)
            if not proceed:
                logging.info("Reboot differe (peer) : %s", reason)
                event_log.record(PEER_STANDDOWN, reason=reason)
                time.sleep(CHECK_INTERVAL)
                continue

            # --- Pre-reboot backup ---
            if backup_configured():
                try:
                    logging.info("Backup pre-reboot...")
                    bresult = unifi_backup(source="pre_reboot")
                    if bresult.ok:
                        event_log.record("backup_pre_reboot", filename=bresult.filename)
                    else:
                        logging.warning("Backup pre-reboot echoue : %s", bresult.error)
                except Exception as e:
                    logging.warning("Erreur backup pre-reboot : %s", e)

            # --- Execute reboot ---
            logging.warning(
                "Seuil atteint (score=%d) -- Lancement du reboot USG (tentative #%d)",
                failure_score,
                consecutive_reboots + 1,
            )
            text, level, ctx = msg.reboot_launching(
                attempt=consecutive_reboots + 1,
                score=failure_score,
                gateway_ok=result.gateway_ok,
                inet_count=result.internet_ok_count,
                inet_total=result.internet_total,
                reboots_today=reboots_today,
                peer_info=peer_info,
            )
            notify(text, level, ctx)

            last_ssh_attempt_time = now
            success = reboot_usg()

            if success:
                last_reboot_time = time.time()
                grace_until = last_reboot_time + POST_REBOOT_GRACE
                failure_score = 0
                consecutive_reboots += 1
                reboots_today += 1
                consecutive_ssh_failures = 0
                outage_reboot_count += 1

                event_log.record(
                    REBOOT, attempt=consecutive_reboots,
                    score=failure_score, reboots_today=reboots_today,
                )
                next_cooldown = compute_effective_cooldown(consecutive_reboots)
                reboot_time_str = datetime.now().strftime("%H:%M:%S")
                logging.info(
                    "Reboot USG envoye a %s -- Grace %ds + Cooldown %s "
                    "(reboots aujourd'hui: %d/%d)",
                    reboot_time_str,
                    POST_REBOOT_GRACE,
                    _format_duration(next_cooldown),
                    reboots_today,
                    MAX_REBOOTS_PER_DAY,
                )

                if reboots_today >= MAX_REBOOTS_PER_DAY:
                    surveillance_only = True
                    event_log.record(MAX_REBOOTS, reboots_today=reboots_today)
                    logging.warning(
                        "Max reboots/jour atteint (%d) -- passage en mode surveillance",
                        MAX_REBOOTS_PER_DAY,
                    )
                    text, level, ctx = msg.max_reboots_reached(reboots_today)
                    notify(text, level, ctx)

                logging.info(
                    "Pause de %ds -- attente du redemarrage USG...",
                    USG_REBOOT_WAIT,
                )
                for _ in range(USG_REBOOT_WAIT):
                    time.sleep(1)
            else:
                consecutive_ssh_failures += 1
                ssh_delay = compute_ssh_retry_delay(consecutive_ssh_failures)

                event_log.record(REBOOT_FAILED, ssh_failures=consecutive_ssh_failures)
                if consecutive_ssh_failures == SSH_FAILURE_BACKOFF_START:
                    text, level, ctx = msg.ssh_failure(
                        consecutive_ssh_failures, _format_duration(ssh_delay),
                    )
                    notify(text, level, ctx)
                logging.error(
                    "Reboot SSH echoue (%d echecs, retry dans %s)",
                    consecutive_ssh_failures,
                    _format_duration(ssh_delay) if ssh_delay > 0 else "30s",
                )

        # --- Periodic DDNS check (rate-limited internally) ---
        if ddns_configured() and failure_score == 0:
            ddns_result = ddns_check()
            if ddns_result and ddns_result.changed:
                if ddns_result.records_failed == 0:
                    text_d, level_d, ctx_d = msg.ddns_updated(
                        ddns_result.previous_ip, ddns_result.current_ip,
                        ddns_result.records_updated,
                        ", ".join(r.strip() for r in __import__("config").CLOUDFLARE_RECORD_NAMES.split(",")),
                    )
                else:
                    text_d, level_d, ctx_d = msg.ddns_failed(
                        ddns_result.current_ip, list(ddns_result.errors),
                    )
                notify(text_d, level_d, ctx_d)
                event_log.record(
                    "dns_updated" if ddns_result.records_failed == 0 else "dns_update_failed",
                    old_ip=ddns_result.previous_ip, new_ip=ddns_result.current_ip,
                    records=ddns_result.records_updated,
                )

        # --- Periodic SNMP check (every 10 cycles = ~5 min) ---
        if cycle_count % 10 == 0:
            try:
                usg_metrics = read_usg_metrics()
                if usg_metrics.reachable and usg_metrics.is_stressed():
                    logging.warning(
                        "USG sous stress : CPU=%s%% RAM=%s%%",
                        usg_metrics.cpu_percent, usg_metrics.memory_percent,
                    )
                    event_log.record(
                        "usg_stressed",
                        cpu=usg_metrics.cpu_percent,
                        ram=usg_metrics.memory_percent,
                    )
            except Exception:
                pass

        # --- Periodic speedtest (every SPEEDTEST_INTERVAL_CYCLES) ---
        if cycle_count % SPEEDTEST_INTERVAL_CYCLES == 0 and failure_score == 0:
            try:
                speed_result = run_speedtest()
                if speed_result.ok:
                    logging.debug(
                        "Speedtest: %.2f Mbps", speed_result.download_mbps or 0
                    )
                    event_log.record(
                        "speedtest",
                        mbps=round(speed_result.download_mbps or 0, 2),
                        duration_ms=speed_result.duration_ms,
                    )
            except Exception:
                pass

        cycle_count += 1

        # Record history data point
        history_buffer.record(failure_score, result.gateway_rtt_ms, result.internet_avg_rtt_ms)

        # Publish state for HTTP server + peer queries
        state_holder.state = WatchdogState(
            failure_score=failure_score,
            threshold=REBOOT_SCORE_THRESHOLD,
            was_degraded=was_degraded,
            last_reboot_time=last_reboot_time,
            grace_until=grace_until,
            consecutive_reboots=consecutive_reboots,
            reboots_today=reboots_today,
            surveillance_only=surveillance_only,
            consecutive_ssh_failures=consecutive_ssh_failures,
            last_ssh_attempt_time=last_ssh_attempt_time,
            isp_outage_detected=isp_outage_detected,
            outage_start_time=outage_start_time,
            outage_reboot_count=outage_reboot_count,
            outage_reboot_helped=outage_reboot_helped,
            threshold_reached_time=threshold_reached_time,
            instance_priority=INSTANCE_PRIORITY,
            gateway_ok=result.gateway_ok,
            internet_ok_count=result.internet_ok_count,
            internet_total=result.internet_total,
            peer_status=str(peer_info.get("status", "unknown")),
            peer_score=int(peer_info.get("score", 0)),
            peer_gateway=str(peer_info.get("gateway", "")),
            peer_internet=str(peer_info.get("internet", "")),
            gateway_rtt_ms=result.gateway_rtt_ms,
            internet_avg_rtt_ms=result.internet_avg_rtt_ms,
            latency_degraded=internet_latency.is_degraded(),
            version=_version,
            timestamp=datetime.now().isoformat(),
            uptime_seconds=time.time() - start_time,
        )

        time.sleep(CHECK_INTERVAL)


_event_log: EventLog | None = None


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.info("USG Watchdog arrete manuellement")
        if _event_log:
            _event_log.record(SHUTDOWN, reason="manual")
            _event_log.persist_now()
        text, level, ctx = msg.shutdown("arret manuel")
        notify(text, level, ctx)
        sys.exit(0)
    except Exception:
        logging.critical("Erreur fatale", exc_info=True)
        if _event_log:
            _event_log.record(SHUTDOWN, reason="crash")
            _event_log.persist_now()
        text, level, ctx = msg.shutdown("crash")
        notify(text, level, ctx)
        sys.exit(1)
