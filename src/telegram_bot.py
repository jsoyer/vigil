"""Telegram bot -- interactive commands via long-polling.

Runs in a background thread. Allows controlling the watchdog from Telegram.
Commands: /status, /pause, /resume, /reboot, /ddns, /backup, /tailscale, /help
/lte est un point d'extension : le dispatcher route ses sous-commandes vers
des handlers enregistres via `register_lte_handler()`. Aucun handler n'est
enregistre par ce module -- ils arrivent avec les commandes TP-Link.
"""

import json
import logging
import threading
import time
import urllib.request
import urllib.error
from typing import Callable

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from state import StateHolder, CMD_PAUSE, CMD_RESUME, CMD_REBOOT

# Handler enregistrable pour une sous-commande /lte : recoit les arguments
# restants (chaine, potentiellement vide), le chat_id et le StateHolder.
LteHandler = Callable[[str, str, StateHolder], None]

_lte_handlers: dict[str, LteHandler] = {}


def register_lte_handler(subcommand: str, handler: LteHandler) -> None:
    """Enregistre un handler pour `/lte <subcommand> [args]`.

    Point d'extension : les commandes TP-Link reelles s'enregistrent ici.
    Ce module ne fournit aucun handler par defaut.
    """
    _lte_handlers[subcommand.strip().lower()] = handler


def _handle_lte(args: str, chat_id: str, holder: StateHolder) -> None:
    """Route `/lte <sous-commande> [reste]` vers son handler enregistre."""
    subcommand, _, rest = args.strip().partition(" ")
    handler = _lte_handlers.get(subcommand.lower())
    if handler is None:
        _send(
            chat_id,
            "Commande LTE indisponible pour le moment.\nTapez /help pour la liste.",
        )
        return
    handler(rest.strip(), chat_id, holder)


def is_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _api(method: str, params: dict | None = None) -> dict | None:
    """Call Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    if params:
        data = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
    else:
        req = urllib.request.Request(url)

    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _send(chat_id: str, text: str) -> None:
    _api("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})


def _handle_command(
    command: str,
    chat_id: str,
    holder: StateHolder,
) -> None:
    """Process a bot command."""
    cmd = command.strip().lower().split("@")[0]  # strip @botname -- inchange
    # cmd_word et lte_args sont calcules a partir du texte brut, pas de `cmd`
    # (qui peut avoir tronque tout ce qui suit un "@" ailleurs dans le
    # message). Ils servent uniquement au routage /lte <sous-commande>
    # [args] ; les 8 commandes existantes continuent de dispatcher sur `cmd`
    # en entier, donc rejettent tout argument en trop exactement comme avant.
    _raw = command.strip().lower()
    _first_token, _, lte_args = _raw.partition(" ")
    cmd_word = _first_token.split("@")[0]  # strip @botname du seul 1er mot

    if cmd == "/status":
        state = holder.state
        if state is None:
            _send(chat_id, "Watchdog en cours de demarrage...")
            return

        if state.surveillance_only:
            status = "SURVEILLANCE"
        elif state.failure_score >= state.threshold:
            status = "CRITIQUE"
        elif state.failure_score > 0:
            status = "DEGRADE"
        else:
            status = "OK"

        lines = [
            "<b>Vigil</b>",
            "",
            f"Status : <b>{status}</b>",
            f"Score : {state.failure_score}/{state.threshold}",
            f"Gateway : {'OK' if state.gateway_ok else 'KO'}",
            f"Internet : {state.internet_ok_count}/{state.internet_total}",
        ]
        if state.gateway_rtt_ms is not None:
            lines.append(f"Latence GW : {round(state.gateway_rtt_ms, 1)}ms")
        if state.internet_avg_rtt_ms is not None:
            lines.append(f"Latence Internet : {round(state.internet_avg_rtt_ms, 1)}ms")
        lines.extend(
            [
                f"Reboots aujourd'hui : {state.reboots_today}",
                f"ISP : {'PANNE' if state.isp_outage_detected else 'OK'}",
                f"Peer : {state.peer_status}",
                f"Uptime : {int(state.uptime_seconds // 3600)}h",
            ]
        )
        _send(chat_id, "\n".join(lines))

    elif cmd == "/pause":
        holder.send_command(CMD_PAUSE)
        _send(
            chat_id,
            "Mode surveillance active. Le watchdog ne redemarrera plus le routeur.",
        )

    elif cmd == "/resume":
        holder.send_command(CMD_RESUME)
        _send(chat_id, "Mode normal reactive. Le watchdog peut redemarrer le routeur.")

    elif cmd == "/reboot":
        holder.send_command(CMD_REBOOT)
        _send(chat_id, "Reboot USG demande. Coupure de ~2 min attendue.")

    elif cmd == "/ddns":
        from ddns_cloudflare import check_and_update, is_configured as ddns_ok

        if not ddns_ok():
            _send(chat_id, "DDNS non configure.")
            return
        result = check_and_update(force=True)
        if result is None:
            _send(chat_id, "Impossible de determiner l'IP publique.")
        elif result.changed:
            _send(
                chat_id, f"IP mise a jour : {result.previous_ip} -> {result.current_ip}"
            )
        else:
            _send(chat_id, f"IP inchangee : {result.current_ip}")

    elif cmd == "/backup":
        from backup_unifi import run_backup, is_configured as backup_ok

        if not backup_ok():
            _send(chat_id, "Backup UniFi non configure.")
            return
        _send(chat_id, "Backup en cours...")
        bresult = run_backup(source="telegram")
        _send(chat_id, bresult.summary())

    elif cmd == "/tailscale":
        from tailscale_dns import sync_tailscale_dns, is_configured as ts_ok

        if not ts_ok():
            _send(chat_id, "Tailscale DNS sync non configure.")
            return
        _send(chat_id, "Sync Tailscale DNS en cours...")
        ts_result = sync_tailscale_dns(force=True)
        if ts_result is None:
            _send(chat_id, "Sync echouee.")
        else:
            _send(chat_id, ts_result.summary())

    elif cmd == "/help":
        _send(
            chat_id,
            "<b>Commandes disponibles :</b>\n\n"
            "/status - Etat du watchdog\n"
            "/pause - Mode surveillance (plus de reboot)\n"
            "/resume - Reprendre le mode normal\n"
            "/reboot - Forcer un reboot USG\n"
            "/ddns - Forcer une MAJ DNS Cloudflare\n"
            "/tailscale - Forcer une sync DNS Tailscale\n"
            "/backup - Lancer un backup UniFi\n"
            "/help - Cette aide",
        )

    elif cmd_word == "/lte":
        # /lte <sous-commande> [args] -- point d'extension, voir _handle_lte.
        # Nouveau : aucune des 8 commandes ci-dessus ne peut matcher "/lte",
        # donc ce branchement ne change rien a leur comportement.
        _handle_lte(lte_args, chat_id, holder)

    else:
        _send(chat_id, f"Commande inconnue : {cmd}\nTapez /help pour la liste.")


class TelegramBot:
    """Long-polling Telegram bot running in a background thread."""

    def __init__(self, holder: StateHolder) -> None:
        self._holder = holder
        self._offset = 0

    def start(self) -> bool:
        """Start the bot in a background thread. Returns True if configured."""
        if not is_configured():
            return False

        thread = threading.Thread(
            target=self._poll_loop,
            name="telegram-bot",
            daemon=True,
        )
        thread.start()
        logging.info("Telegram bot demarre (long-polling)")
        return True

    def _poll_loop(self) -> None:
        while True:
            try:
                self._poll_updates()
            except Exception as e:
                logging.debug("Telegram bot poll error: %s", e)
                time.sleep(10)

    def _poll_updates(self) -> None:
        result = _api(
            "getUpdates",
            {
                "offset": self._offset,
                "timeout": 30,
                "allowed_updates": ["message"],
            },
        )

        if result is None or not result.get("ok"):
            time.sleep(5)
            return

        for update in result.get("result", []):
            self._offset = update["update_id"] + 1
            message = update.get("message", {})
            text = message.get("text", "")
            chat_id = str(message.get("chat", {}).get("id", ""))

            # Security: only respond to the configured chat
            if chat_id != TELEGRAM_CHAT_ID:
                logging.warning("Telegram bot: message ignore de chat_id non autorise")
                continue

            if text.startswith("/"):
                _handle_command(text, chat_id, self._holder)
