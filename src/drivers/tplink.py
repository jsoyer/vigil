"""Driver TP-Link MR110 -- implementation concrete du contrat `RouterDriver`.

Voir `docs/spikes/2026-08-23-mr110-compat.md` (verdict FULL, lib validee sur
materiel reel aux deux sites) et
`docs/tasks/router/feature/2026-08-20_1618-a1-pilotage-tplink/sprints/02-tplink-driver.md`.

Invariant C1 -- import vendor paresseux, non negociable : `tplinkrouterc6u`
n'est importe **nulle part** au niveau module, uniquement dans le corps de
`_default_client_factory`. `updater/preflight.py` importe `watchdog`, qui
importe `config`, qui (via ce module si un equipement est declare) ne doit
jamais tirer la lib vendor -- une chaine d'import qui la tire ferait echouer
le preflight -> update avortee + rollback sur les 4 instances de production.
Voir INVARIANTS.md, "Import vendor paresseux (C1)".

Ce module n'appelle **jamais** `reboot()` automatiquement : seule une
commande operateur explicite et confirmee (cablee au Sprint 3) le declenche
(C6).
"""

import logging
import re
import subprocess
import time
from enum import Enum
from typing import Any, Callable

from ddns_cloudflare import get_public_ip

from ._base import Hop, Readiness, RouterHealth, RouterMetrics, RouterReadiness

# Interface utilisee pour le binding de la sonde de bout en bout (C11,
# `_probe_command`) uniquement -- l'etage BRIDGE en mode `bridged` ne s'y fie
# plus depuis le bugfix 2026-08-22 (voir `_default_route_check`) : le lien
# reel vers le MR110 varie selon le parc (WiFi, ethernet, vlan...) et coder
# `wlan0` en dur y produisait un faux negatif sur les guardians ou ce n'est
# pas l'interface reellement utilisee.
# Non exposee via une variable d'environnement dans ce sprint (la liste des
# variables TPLINK_<n>_* est fixee par la spec : HOST, LABEL, PASSWORD,
# BRIDGE_HOST, MODE, RSRP_MIN, RSRQ_MIN, SNR_MIN) -- constante isolee ici pour
# rester facilement overridable plus tard si le parc en a besoin.
DEFAULT_WIFI_IFACE = "wlan0"

DEFAULT_TIMEOUT = 8.0
DEFAULT_PROBE_CACHE_TTL = 60.0

# `ip route get` est une resolution locale au noyau -- quasi instantanee.
# Timeout court et independant du timeout reseau (SSH/ping) pour ne jamais
# faire trainer l'etage BRIDGE en mode `bridged`.
DEFAULT_ROUTE_CHECK_TIMEOUT = 2.0

_ROUTE_DEV_RE = re.compile(r"\bdev\s+\S+")

# SIM consideree operationnelle : valeur observee sur les deux MR110 reels
# lors du spike (Dijon et Nice, service fonctionnel). La lib ne documentant
# pas l'enum complet des codes `sim_status`, toute autre valeur connue est
# traitee comme non prete plutot que supposee bonne (politique
# d'incertitude du PRD : ne jamais se replier sur un etat sain).
_SIM_OK_VALUE = "3"

_IP_LIKE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


class ProbeResult(str, Enum):
    """Resultat de la sonde de bout en bout (C11) -- quatre valeurs.

    Voir INVARIANTS.md, "La sonde de bout en bout sort par le lien 4G (C11)".
    """

    OK = "ok"  # data qui passe, chemin prouve
    FAIL = "fail"  # pas de data sur le lien -- DEGRADED
    LEAK = "leak"  # sortie par la fibre -- defaut de config du chemin de test
    UNKNOWN = "unknown"  # pont/SSH injoignable, commande absente


def _import_tplinkrouterc6u():
    """Import paresseux de la lib vendor (invariant C1).

    N'est appele que depuis `_default_client_factory`, jamais au niveau
    module.
    """
    import tplinkrouterc6u

    return tplinkrouterc6u


def _get(obj: Any, name: str) -> Any:
    """Lecture best-effort d'un champ, quel que soit le type de retour de la
    lib (objet, dataclass, ou dict) -- ne leve jamais, renvoie `None` si le
    champ est absent ou d'un type inattendu."""
    if obj is None:
        return None
    try:
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)
    except Exception:
        return None


def _safe_call(fn: Callable[[], Any]) -> Any:
    """Appelle `fn()` en absorbant toute exception -- renvoie `None` si echec."""
    try:
        return fn()
    except Exception:
        return None


def _default_ping(host: str, timeout: float) -> tuple[bool, float | None]:
    """Ping ICMP via la commande systeme. Ne leve jamais."""
    try:
        start = time.monotonic()
        completed = subprocess.run(
            ["ping", "-c", "1", "-W", str(max(1, int(timeout))), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
        )
        elapsed_ms = (time.monotonic() - start) * 1000
    except Exception:
        return False, None
    if completed.returncode != 0:
        return False, None
    return True, elapsed_ms


def _default_route_check(host: str, timeout: float) -> tuple[bool, float | None]:
    """Verifie qu'une route locale existe vers `host` (mode `bridged`), via
    `ip route get` -- resout la route reellement empruntee par le noyau,
    quel que soit le type d'interface (WiFi, ethernet, vlan...). Remplace
    l'ancien check `iw dev wlan0 link` (bugfix 2026-08-22) qui produisait un
    faux negatif des que le lien vers le MR110 n'etait pas porte par wlan0.
    Timeout court et plafonne (`DEFAULT_ROUTE_CHECK_TIMEOUT`) : une
    resolution de route locale ne devrait jamais trainer. Ne leve jamais."""
    try:
        completed = subprocess.run(
            ["ip", "route", "get", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=min(timeout, DEFAULT_ROUTE_CHECK_TIMEOUT),
            text=True,
        )
    except Exception:
        return False, None
    if completed.returncode != 0:
        return False, None
    if not _ROUTE_DEV_RE.search(completed.stdout or ""):
        return False, None
    return True, None


def _default_local_command(command: str, timeout: float) -> tuple[bool, str]:
    """Execute une commande localement (mode `bridged`). Ne leve jamais."""
    try:
        completed = subprocess.run(
            ["sh", "-c", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            text=True,
        )
    except Exception:
        return False, ""
    return completed.returncode == 0, (completed.stdout or "")


def _default_ssh_command(client: Any, command: str, timeout: float) -> tuple[bool, str]:
    """Execute une commande SSH ponctuelle sur le pont (mode `remote`, C7/C11).
    Ne leve jamais."""
    try:
        _, stdout, _stderr = client.exec_command(command, timeout=timeout)
        output = stdout.read().decode("utf-8", errors="replace")
        exit_status = stdout.channel.recv_exit_status()
    except Exception:
        return False, ""
    return exit_status == 0, output


class TplinkDriver:
    """Driver TP-Link MR110 conforme au Protocol `RouterDriver`.

    Aucune methode ne leve jamais (invariant "Les drivers ne levent jamais",
    INVARIANTS.md) : toute defaillance se traduit par une valeur degradee
    (`None`, `Readiness.UNKNOWN`, `False`), jamais par une exception ni par
    un etat sain invente par defaut.

    Le mode d'acces (`bridged` / `remote`, C16) est isole derriere une petite
    abstraction d'execution : seules `_check_bridge` (saut BRIDGE) et
    `_run_probe_command` (sonde C11) different selon le mode -- le reste de
    la sonde (WIRELESS, DEVICE, preuve de chemin) est strictement identique.

    Toutes les dependances externes (ping, verification WiFi, execution SSH
    ou locale, creation du client vendor, IP publique du site) sont
    injectables au constructeur pour permettre des tests entierement
    mockes, sans acces reseau (voir tests/test_drivers_tplink.py).
    """

    vendor = "tplink"

    def __init__(
        self,
        host: str,
        password: str,
        *,
        label: str = "",
        mode: str = "bridged",
        bridge_host: str = "",
        rsrp_min: int = -110,
        rsrq_min: int = -20,
        snr_min: int = -100,
        timeout: float = DEFAULT_TIMEOUT,
        probe_cache_ttl: float = DEFAULT_PROBE_CACHE_TTL,
        client_factory: Callable[[], Any] | None = None,
        ping_fn: Callable[[str, float], tuple[bool, float | None]] | None = None,
        route_check_fn: Callable[[str, float], tuple[bool, float | None]] | None = None,
        ssh_client_factory: Callable[[], Any] | None = None,
        ssh_command_fn: Callable[[Any, str, float], tuple[bool, str]] | None = None,
        local_command_fn: Callable[[str, float], tuple[bool, str]] | None = None,
        get_public_ip_fn: Callable[[], str | None] | None = None,
    ) -> None:
        self.host = host
        self.password = password
        self.label = label or host
        self.bridge_host = bridge_host
        self.rsrp_min = rsrp_min
        self.rsrq_min = rsrq_min
        self.snr_min = snr_min
        self.timeout = timeout
        self.probe_cache_ttl = probe_cache_ttl

        normalized_mode = (mode or "bridged").strip().lower()
        if normalized_mode not in ("bridged", "remote"):
            logging.warning(
                "TPLINK '%s' : mode invalide ('%s'), repli sur 'bridged'",
                self.label,
                normalized_mode,
            )
            normalized_mode = "bridged"
        self.mode = normalized_mode

        self._client_factory = client_factory or self._default_client_factory
        self._ping_fn = ping_fn or _default_ping
        self._route_check_fn = route_check_fn or _default_route_check
        self._ssh_client_factory = (
            ssh_client_factory or self._default_ssh_client_factory
        )
        self._ssh_command_fn = ssh_command_fn or _default_ssh_command
        self._local_command_fn = local_command_fn or _default_local_command
        self._get_public_ip_fn = get_public_ip_fn or get_public_ip

        # Etat process-lifetime (non persiste au redemarrage) : sert
        # uniquement a C8 (distinguer "jamais joignable" de "plus
        # joignable") et au cache de la sonde C11.
        self._ever_reachable = False
        self._last_probe_result: ProbeResult | None = None
        self._last_probe_time: float = 0.0
        self._last_known_site_ip: str | None = None

    # ------------------------------------------------------------------
    # Defauts reels (non utilises si un equivalent est injecte, cf. tests)
    # ------------------------------------------------------------------

    def _default_client_factory(self) -> Any:
        tplinkrouterc6u = _import_tplinkrouterc6u()
        return tplinkrouterc6u.TplinkRouterProvider.get_client(self.host, self.password)

    def _default_ssh_client_factory(self) -> Any:
        """SSH ponctuel vers le pont (mode `remote`) -- reutilise l'identite
        SSH deja en place pour l'USG (meme cle/known_hosts, poses par
        `scripts/setup_ssh.sh` sur le pont au Sprint 1) plutot que d'ajouter
        de nouvelles variables TPLINK_*_SSH_* hors de la liste fixee par la
        spec. Rien n'est installe sur le pont (C7) : une seule commande
        ponctuelle est executee puis la connexion est fermee."""
        import paramiko

        import config

        client = paramiko.SSHClient()
        if config.USG_KNOWN_HOSTS:
            try:
                client.load_host_keys(config.USG_KNOWN_HOSTS)
            except Exception:
                pass
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        connect_kwargs: dict[str, Any] = {
            "username": config.USG_USER,
            "timeout": config.SSH_TIMEOUT,
        }
        if config.USG_SSH_KEY:
            connect_kwargs["key_filename"] = config.USG_SSH_KEY
        elif config.USG_SSH_PASSWORD:
            connect_kwargs["password"] = config.USG_SSH_PASSWORD
        client.connect(self.bridge_host, **connect_kwargs)
        return client

    # ------------------------------------------------------------------
    # Session TP-Link : authorize() -> action -> logout() garanti (C5)
    # ------------------------------------------------------------------

    def _with_session(self, action: Callable[[Any], Any]) -> tuple[bool, Any]:
        """Execute `action(client)` dans une session TP-Link. `logout()` est
        garanti en `finally`, y compris si `authorize()` ou `action` levent.
        Ne journalise jamais le contenu d'une exception (peut contenir le
        mot de passe) -- uniquement son type."""
        try:
            client = self._client_factory()
        except Exception as exc:
            logging.warning(
                "TPLINK '%s' : creation du client KO (%s)",
                self.label,
                type(exc).__name__,
            )
            return False, None

        try:
            client.authorize()
            result = action(client)
            return True, result
        except Exception as exc:
            logging.warning(
                "TPLINK '%s' : session KO (%s)", self.label, type(exc).__name__
            )
            return False, None
        finally:
            try:
                client.logout()
            except Exception as exc:
                logging.debug(
                    "TPLINK '%s' : logout() KO (%s)", self.label, type(exc).__name__
                )

    # ------------------------------------------------------------------
    # Sonde etagee -- attribution de panne (BRIDGE / WIRELESS / DEVICE / ROUTE)
    # ------------------------------------------------------------------

    def _check_bridge(self) -> tuple[bool, float | None, str]:
        if self.mode == "remote":
            if not self.bridge_host:
                return False, None, "TPLINK_*_BRIDGE_HOST absent en mode remote"
            ok, rtt = self._ping_fn(self.bridge_host, self.timeout)
            detail = (
                ""
                if ok
                else (
                    f"Pont '{self.bridge_host}' injoignable -- cause possible : "
                    "hote pont, port PoE, budget PoE ou cable (a diagnostiquer sur site)"
                )
            )
            return ok, rtt, detail

        ok, rtt = self._route_check_fn(self.host, self.timeout)
        detail = (
            ""
            if ok
            else (
                f"Pas de route locale vers le MR110 '{self.label}' -- "
                "interface reseau locale down ou non configuree (verifier "
                f"'ip route get {self.host}' sur cette machine)"
            )
        )
        return ok, rtt, detail

    def health(self) -> RouterHealth:
        """Sonde de joignabilite avec attribution de panne. Ne leve jamais.

        L'etage BRIDGE est un signal de diagnostic, jamais un veto (bugfix
        2026-08-22) : un echec de resolution de route locale ne bloque pas la
        suite de la sonde. Il n'est attribue comme `failed_hop` que si le
        device ne repond PAS non plus au ping -- sinon un etage anterieur en
        echec "soft" contredirait un device qui repond reellement (auth +
        metriques OK), ce qui rendrait `reachable` incoherent avec la
        realite observee par les etages suivants.
        """
        bridge_ok, bridge_rtt, bridge_detail = self._check_bridge()

        wireless_ok, wireless_rtt = self._ping_fn(self.host, self.timeout)
        if not wireless_ok:
            if not bridge_ok:
                # Route locale absente ET device injoignable : l'etage
                # BRIDGE est la cause la plus actionnable, on l'attribue.
                return RouterHealth(
                    reachable=False,
                    internet_ok=None,  # type: ignore[arg-type]
                    rtt_ms=bridge_rtt,
                    failed_hop=Hop.BRIDGE,
                    detail=bridge_detail,
                )
            if self.mode == "remote" and not self._ever_reachable:
                # C8 : jamais joignable depuis cette instance -> defaut de
                # configuration (route/NAT absents), pas une panne du secours.
                return RouterHealth(
                    reachable=False,
                    internet_ok=None,  # type: ignore[arg-type]
                    rtt_ms=None,
                    failed_hop=Hop.ROUTE,
                    detail=(
                        f"MR110 '{self.label}' jamais joignable depuis cette "
                        "instance -- route ou NAT probablement absents sur le "
                        "pont (defaut de configuration, pas une panne du secours)"
                    ),
                )
            return RouterHealth(
                reachable=False,
                internet_ok=None,  # type: ignore[arg-type]
                rtt_ms=None,
                failed_hop=Hop.WIRELESS,
                detail=(
                    f"MR110 '{self.label}' injoignable "
                    "(lien WiFi decroche ou routeur eteint)"
                ),
            )

        self._ever_reachable = True

        if not bridge_ok:
            # Le device repond au ping malgre un etage BRIDGE en echec : ne
            # jamais laisser ce signal anterieur contredire un secours sain.
            # Reste un defaut de configuration local a diagnostiquer (route
            # absente alors que le device est joignable par un autre chemin),
            # journalise pour observabilite mais n'affecte pas `reachable`.
            logging.info(
                "TPLINK '%s' : etage bridge en echec (%s) mais le device "
                "repond au ping -- signal ignore pour 'reachable'",
                self.label,
                bridge_detail,
            )

        authorized, _ = self._with_session(lambda client: None)
        if not authorized:
            return RouterHealth(
                reachable=False,
                internet_ok=None,  # type: ignore[arg-type]
                rtt_ms=wireless_rtt,
                failed_hop=Hop.DEVICE,
                detail=f"MR110 '{self.label}' repond au ping mais pas a l'admin",
            )

        return RouterHealth(
            reachable=True,
            internet_ok=self._cached_probe_internet_ok(),  # type: ignore[arg-type]
            rtt_ms=wireless_rtt,
            failed_hop=None,
            detail="chemin d'audit sain",
        )

    # ------------------------------------------------------------------
    # Metriques
    # ------------------------------------------------------------------

    def _collect_metrics(self, client: Any) -> RouterMetrics:
        lte = _safe_call(client.get_lte_status)
        status = _safe_call(client.get_status)
        return RouterMetrics(
            cpu_usage=_get(status, "cpu_usage"),
            mem_usage=_get(status, "mem_usage"),
            # wan_ip : champ non confirme au spike (point ouvert #1,
            # docs/spikes/2026-08-23-mr110-compat.md) -- plusieurs noms
            # candidats tentes best-effort, jamais suppose.
            wan_ip=(
                _get(status, "wan_ipv4_addr")
                or _get(status, "wan_ip")
                or _get(status, "ip")
            ),
            clients_total=_get(status, "clients_total"),
            network_type=_get(lte, "network_type"),
            sim_status=_get(lte, "sim_status"),
            signal_bars=_get(lte, "sig_level"),
            rsrp=_get(lte, "rsrp"),
            rsrq=_get(lte, "rsrq"),
            snr=_get(lte, "snr"),
            isp_name=_get(lte, "isp_name"),
            data_used_bytes=_get(lte, "total_statistics"),
            rx_speed_bps=_get(lte, "cur_rx_speed"),
            tx_speed_bps=_get(lte, "cur_tx_speed"),
        )

    def metrics(self) -> RouterMetrics:
        """Metriques best-effort. Ne leve jamais -- champs a `None` si indispo."""
        ok, result = self._with_session(self._collect_metrics)
        if not ok or result is None:
            return RouterMetrics()
        return result

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------

    def readiness(self) -> RouterReadiness:
        """Etat de disponibilite calcule. Ne leve jamais -- `UNKNOWN` si indispo.

        Seuils RSRP/RSRQ documentes (unites LTE standard). Le SNR firmware
        n'entre pas dans la readiness : son echelle n'est pas un SINR en dB
        (voir commentaire ci-dessous).
        """
        ok, metrics = self._with_session(self._collect_metrics)
        if not ok or metrics is None:
            return RouterReadiness(
                state=Readiness.UNKNOWN,
                reasons=(),
            )

        reasons: list[str] = []
        unknown = False

        if metrics.sim_status is None:
            unknown = True
        elif str(metrics.sim_status) != _SIM_OK_VALUE:
            reasons.append(f"sim_status={metrics.sim_status!r} (SIM non prete)")

        # RSRP : coherent avec les valeurs mesurees au spike (-99 Dijon,
        # -103 Nice, service fonctionnel a 3/5 barres) -- -110 dBm est un
        # seuil standard LTE "limite utilisable".
        # `isinstance` (plutot que `is None`) couvre aussi tout type
        # inattendu renvoye par la lib -- un driver ne leve jamais, meme
        # face a un firmware qui renverrait un champ mal type.
        if not isinstance(metrics.rsrp, (int, float)):
            unknown = True
        elif metrics.rsrp < self.rsrp_min:
            reasons.append(f"rsrp={metrics.rsrp} < seuil {self.rsrp_min}")

        # RSRQ : plage LTE typique -3 (excellent) a -19.5 (limite) ; -20
        # laisse une marge sur les valeurs observees au spike (-14 Dijon,
        # -18 Nice, toutes deux avec service fonctionnel) sans etre inoperant.
        if not isinstance(metrics.rsrq, (int, float)):
            unknown = True
        elif metrics.rsrq < self.rsrq_min:
            reasons.append(f"rsrq={metrics.rsrq} < seuil {self.rsrq_min}")

        # SNR : l'echelle remontee par le firmware du MR110 n'est pas un
        # SINR LTE en dB (spike 2026-08-23 : -20 Dijon / -70 Nice, deux
        # liens fonctionnels a 3/5 barres). En production le firmware
        # pousse aussi une sentinelle -130 (radio idle / mesure absente)
        # qui passait sous le seuil "conservateur" -100 et declenchait un
        # faux DEGRADED, puis un "de nouveau pret" au cycle suivant.
        # Le champ reste lu et expose (dashboard, metriques) ; il ne
        # participe plus a la readiness. RSRP/RSRQ suffisent -- ce sont
        # les seules unites LTE confirmees. self.snr_min est conserve
        # pour ne pas casser TPLINK_<n>_SNR_MIN dans les .env existants.

        probe = self._cached_probe_result()
        if probe is ProbeResult.FAIL:
            reasons.append(
                "sonde de bout en bout : pas de data sur le lien "
                "(attache mais forfait/APN en cause ?)"
            )
        # LEAK : defaut de config du chemin de test, PAS une panne du
        # secours -- ne degrade pas la readiness (deja notifie via
        # tplink_probe_leak). UNKNOWN / pas de sonde : idem.

        if reasons:
            return RouterReadiness(state=Readiness.DEGRADED, reasons=tuple(reasons))
        if unknown:
            return RouterReadiness(state=Readiness.UNKNOWN, reasons=())
        return RouterReadiness(state=Readiness.OK, reasons=())

    # ------------------------------------------------------------------
    # Sonde de bout en bout (C11) -- preuve de chemin, 4 valeurs
    # ------------------------------------------------------------------

    def _probe_command(self) -> str:
        """Commande executee sur l'hote qui porte l'interface WiFi vers le
        MR110 (le pont lui-meme en mode `remote`, ou l'hote local en mode
        `bridged`) -- strictement identique dans les deux modes (C16) ;
        seule son execution (locale ou SSH) differe. Le binding a l'interface
        ne prouve rien a lui seul (cf. double preuve ci-dessous)."""
        return (
            f"curl -s --max-time {max(1, int(self.timeout))} "
            f"--interface {DEFAULT_WIFI_IFACE} https://ifconfig.me"
        )

    def _run_probe_command(self) -> tuple[bool, str | None]:
        """Execute la commande de sonde. Renvoie (invoked, ip) :
        `invoked=False` si le mecanisme d'execution lui-meme est injoignable
        (pont/SSH down) -> UNKNOWN ; `invoked=True, ip=None` si la commande a
        tourne mais n'a rien renvoye d'exploitable -> FAIL."""
        command = self._probe_command()

        if self.mode == "remote":
            try:
                client = self._ssh_client_factory()
            except Exception as exc:
                logging.warning(
                    "TPLINK '%s' : SSH vers le pont KO (%s)",
                    self.label,
                    type(exc).__name__,
                )
                return False, None
            try:
                ok, output = self._ssh_command_fn(client, command, self.timeout)
            except Exception:
                return False, None
            finally:
                _safe_call(getattr(client, "close", lambda: None))
        else:
            try:
                ok, output = self._local_command_fn(command, self.timeout)
            except Exception:
                return False, None

        if not ok:
            return True, None
        ip = (output or "").strip()
        if not _IP_LIKE.match(ip):
            return True, None
        return True, ip

    def _get_site_public_ip(self) -> str | None:
        ip = _safe_call(self._get_public_ip_fn)
        if ip:
            self._last_known_site_ip = ip
            return ip
        return self._last_known_site_ip

    def _record_probe(self, result: ProbeResult) -> ProbeResult:
        self._last_probe_result = result
        self._last_probe_time = time.monotonic()
        return result

    def _cached_probe_result(self) -> ProbeResult | None:
        if self._last_probe_result is None:
            return None
        if time.monotonic() - self._last_probe_time > self.probe_cache_ttl:
            return None
        return self._last_probe_result

    def _cached_probe_internet_ok(self) -> bool | None:
        probe = self._cached_probe_result()
        if probe is ProbeResult.OK:
            return True
        if probe is ProbeResult.FAIL:
            return False
        return None  # LEAK, UNKNOWN, ou pas de sonde recente

    def probe_end_to_end(self, record: bool = True) -> ProbeResult:
        """Sonde de bout en bout (C11) : verifie que le lien 4G porte
        reellement du trafic, avec double preuve de chemin independante --
        IP publique observee differente de celle du site, ET compteurs de
        trafic du MR110 en mouvement. Un succes n'est retenu que si les deux
        concordent ; sinon, LEAK (jamais un faux OK). Ne leve jamais, ne
        bloque pas au-dela du timeout.

        `record=False` : resultat renvoye au caller (bouton Verifier) sans
        ecrire le cache lu par `readiness()` -- sinon un FAIL/LEAK de
        diagnostic empoisonne la readiness ~60s et declenche backup_degraded.
        """
        result = self._run_end_to_end_probe()
        if record:
            return self._record_probe(result)
        return result

    def _run_end_to_end_probe(self) -> ProbeResult:
        ok_before, before_counters = self._with_session(
            lambda c: _get(_safe_call(c.get_status), "total_statistics")
        )
        if not ok_before:
            return ProbeResult.UNKNOWN

        invoked, observed_ip = self._run_probe_command()
        if not invoked:
            return ProbeResult.UNKNOWN
        if not observed_ip:
            return ProbeResult.FAIL

        ok_after, after_counters = self._with_session(
            lambda c: _get(_safe_call(c.get_status), "total_statistics")
        )
        counters_moved = bool(
            ok_after
            and before_counters is not None
            and after_counters is not None
            and after_counters != before_counters
        )

        site_ip = self._get_site_public_ip()
        if site_ip is None:
            return ProbeResult.UNKNOWN

        if observed_ip == site_ip or not counters_moved:
            return ProbeResult.LEAK

        return ProbeResult.OK

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def reboot(self) -> bool:
        """Redemarre le MR110. Ne leve jamais.

        Aucun appel automatique depuis ce module : uniquement invoque par une
        commande operateur explicite et confirmee (C6), cablee au Sprint 3.
        """
        ok, result = self._with_session(lambda c: bool(_safe_call(c.reboot)))
        return bool(ok and result)

    def test_connection(self) -> bool:
        """Diagnostic de connexion, sans effet de bord destructif. Ne leve jamais."""
        ok, _ = self._with_session(lambda c: True)
        return ok
