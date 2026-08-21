# Sprint 1 — Chemin réseau Pi Zero + spike TL-MR110 + contrat `RouterDriver`

- **PRD** : Lignes de secours TP-Link MR110 — phase A (management) — 2026-08-12
- **Dépend de** : rien
- **Bloque** : sprints 2 à 5
- **Nature** : **gate go/no-go** — le reste du PRD dépend du chemin réseau *et* du verdict

## Contexte (tout ce qu'il faut savoir, ne pas lire le PRD)

`usg-watchdog` surveille un routeur Ubiquiti USG par site. On veut y ajouter le
**pilotage et l'audit de lignes de secours 4G TP-Link TL-MR110** présentes à
Dijon et Nice, via la lib Python `tplinkrouterc6u`.

Deux inconnues bloquent tout, et ce sprint existe pour les lever.

**Inconnue 1 — il n'y a aucun chemin réseau vers les MR110.** Aucun MR110 n'est
sur le LAN du site. Chacun est sur **son propre réseau WiFi**. Le seul point de
contact est un **Pi Zero 2 W** par site : `eth0` sur le LAN du site, `wlan0`
associé au WiFi du MR110. Il sert de **pont de management uniquement** — il ne
route pas le trafic de production.

```
[ watchdog master ] [ watchdog slave ]        ← LAN du site
          └──────┬──────┘
                 │ route statique : <subnet MR110> via <IP LAN du Pi Zero>
          [ Pi Zero 2 W ]   eth0=LAN   wlan0=WiFi du MR110
                 │          IP forwarding + NAT
             ((( WiFi )))
          [ TL-MR110 ]      cible à piloter
```

**Inconnue 2 — le TL-MR110 indoor n'est pas un modèle testé de la lib.** Seul le
TL-MR110-**Outdoor** v1.0 figure dans la liste des modèles testés (avec MR100,
MR105, MR150, MR6400, Archer MR200/400/550/600). On ne sait pas si
`authorize()` / `get_lte_status()` / `reboot()` fonctionnent sur ce firmware.
Écrire un driver avant de le savoir serait écrire dans le vide.

## Objectifs

1. **Réseau** : rendre les MR110 joignables depuis les hôtes watchdog.
2. **Spike** : établir le verdict de compatibilité sur matériel réel.
3. **Contrat** : créer `src/drivers/_base.py`.

L'ordre est impératif : sans (1), (2) ne peut pas tourner.

## Travail — partie A : chemin réseau (à faire en premier)

### A.0 — Choisir la topologie du chemin d'audit (avant de figer quoi que ce soit)

Le TL-MR110 dispose de **2 ports LAN Ethernet**, et son WiFi est en **2,4 GHz
mono-bande** — le maillon le plus fragile du chemin. Le saut WiFi n'est donc pas
une fatalité matérielle.

**Relever d'abord la disposition physique, par site** : le Pi Zero est alimenté
en **PoE**, donc posé là où arrive le câble ; le MR110 est posé là où passe la
4G. Le pont WiFi existe très probablement parce que ces deux points ne
coïncident pas. Noter la distance réelle entre les deux, et où aboutit la
desserte PoE — c'est ce qui rend les variantes ci-dessous possibles ou non.
Aucune ne se tranche sur des critères techniques avant ce relevé.

Évaluer ensuite, avant de câbler :

- **(a) Pi Zero relié au MR110 par Ethernet** plutôt qu'en WiFi. Pont et routage
  inchangés, saut fiabilisé. *Contrainte* : le Pi Zero 2 W n'a pas d'Ethernet
  natif — la liaison LAN passe déjà par un adaptateur USB, il en faudrait un
  second (donc un hub).
- **(c) statu quo** — WiFi, comme aujourd'hui. Si les deux équipements sont
  éloignés, c'est l'option par défaut et il n'y a pas d'arbitrage à rendre.

> **Décision déjà prise (2026-08-12) : le Pi Zero 2 W est conservé.** Toute
> variante qui le supprimerait du chemin (raccordement direct du MR110 au LAN)
> est **écartée** — ne pas la reproposer. Elle exposerait de surcroît l'admin du
> MR110 à tout le LAN du site, ce que C7 cherche à éviter. Seule la **nature du
> saut** Pi Zero ↔ MR110 reste ouverte.

**Le code est indifférent à ce choix** (C7 : le driver parle à une IP). Trancher
sur des critères d'infrastructure et consigner la variante retenue **par site**
dans le runbook — les deux sites peuvent légitimement différer. Dans les deux
cas, le pont, le NAT et la route restent en place : seule la nature du saut
change, et `Hop.WIRELESS` garde son sens (un lien Ethernet peut aussi tomber).

### A.1 — Mise en œuvre

Sur le Pi Zero de Dijon, puis rejouer à l'identique sur Nice :

- Activer l'**IP forwarding** et le **NAT** de `eth0` vers `wlan0`, de façon
  **persistante au reboot** (une conf qui ne survit pas au redémarrage est une
  panne différée).
- Poser une **route statique** vers le subnet du MR110 via l'IP LAN du Pi Zero,
  **sur les hôtes watchdog uniquement** — pas sur l'USG, pas en DHCP. Motif de
  sécurité (C7) : l'interface d'administration du MR110 ne doit pas devenir
  joignable depuis tout le LAN du site.
- Rendre la route persistante côté hôte watchdog.
- Vérifier depuis un hôte watchdog : ping du Pi Zero, ping du MR110, accès HTTP
  à l'interface d'administration du MR110.

Documenter la procédure **exacte et reproductible** dans
`docs/runbooks/pi-zero-mr110-access.md` : commandes, fichiers de conf modifiés,
adressage relevé par site, méthode de vérification, et **méthode de rollback**.
Cette procédure sera rejouée par un humain sur le second site et après toute
réinstallation d'un Pi Zero — elle doit être suivable sans deviner.

Relever et consigner, par site : subnet et IP du MR110, IP LAN et IP WiFi du Pi
Zero, SSID, et l'IP source vue par le MR110 après NAT.

**Ne rien installer sur le Pi Zero** (ni Python, ni la lib TP-Link) : C7 impose
que le Pi Zero reste un simple routeur de management, sans code à maintenir.

## Travail — partie B : spike

`scripts/spike_tplink.py`, script **jetable, hors production**, exécuté
manuellement **depuis un hôte watchdog** (donc à travers le chemin complet —
c'est le chemin réel qui est validé, pas un raccourci depuis le Pi Zero) :

```
python3 scripts/spike_tplink.py --host <ip_mr110> [--json-out rapport.json]
```

Tenter, dans l'ordre, en isolant chaque échec :

1. `TplinkRouterProvider.get_client(host, password)` → quelle classe cliente
   (`TPLinkMRClient` ? `TPLinkMRClientGCM` ? exception ?)
2. `authorize()`
3. `get_firmware()` → modèle et version de firmware exacts
4. `get_status()` → champs disponibles
5. `get_lte_status()` → **capturer le dict brut**, champ par champ
6. Inventorier les **commandes de management** réellement disponibles sur ce
   firmware : `reboot`, `get_sms` / `send_sms` / `set_sms_read` / `delete_sms`,
   `send_ussd`, contrôle WiFi. C'est ce que le Sprint 3 exposera à l'opérateur —
   il faut savoir ce qui répond avant de promettre une commande.
7. `logout()` en `finally` — **obligatoire** (session admin unique)

Contraintes :
- Mot de passe par variable d'environnement, jamais en argument de ligne de
  commande, **jamais** loggé ni écrit dans le rapport.
- `logout()` garanti par `try/finally`.
- **Ne PAS appeler `reboot()` automatiquement** : le mettre derrière un flag
  `--allow-reboot` explicite, hors heures de production.
- Idem pour `send_sms` / `send_ussd` : ces commandes coûtent de l'argent ou
  consomment du forfait. Flag explicite, jamais par défaut.

## Travail — partie C : rapport de spike

`docs/spikes/2026-08-XX-mr110-compat.md` :

- **Révision matérielle et version de firmware exactes**, relevées par site. Le
  modèle est un **TL-MR110 indoor** (confirmé — ce n'est pas un MR100, qui lui
  serait couvert par la lib). Il n'existe donc **aucun scénario de repli
  matériel** : ce verdict porte tout le PRD, phase A et évolution WAN2 comprises.
  La révision matérielle reste à relever : c'est le seul axe sur lequel deux
  exemplaires peuvent différer, et la lib distingue explicitement les révisions
  pour d'autres modèles de la série (MR6400 v5 / v5.3 / v7, MR200 v2 / v5 / v6…).
- Classe cliente auto-détectée.
- **Verdict explicite**, une seule valeur :
  - `FULL` — auth + LTE status + commandes de management exploitables
  - `DEGRADED` — auth OK, mais champs ou commandes partiels
  - `UNSUPPORTED` — auth impossible

  *Pronostic, à ne pas confondre avec un résultat* : le TL-MR110 indoor est le
  frère de gamme du TL-MR100 et du TL-MR105, **tous deux dans les modèles
  testés**, et de la variante Outdoor du MR110 elle aussi testée. Même famille
  de firmware, donc chances raisonnables que `TPLinkMRClient` (ou sa variante
  GCM) réponde. Ça ne dispense de rien : c'est justement ce que le spike vérifie.
- Tableau des champs `LTEStatus` disponibles (`rsrp`, `rsrq`, `snr`,
  `network_type`, `sim_status`, `sig_level`, `isp_name`, `total_statistics`,
  `cur_rx_speed`, `cur_tx_speed`, `sms_unread_count`) : présent / absent / nul.
- Tableau des **commandes disponibles** → c'est l'entrée du Sprint 3.
- **Version de lib retenue** (celle qui a marché) → à pinner au Sprint 2.
- **Plan B écrit** si `DEGRADED` ou `UNSUPPORTED` : quel niveau de management
  reste atteignable (au minimum : joignabilité + attribution de panne par saut),
  assez précis pour re-cadrer les sprints 2 à 5.

Si le verdict est `UNSUPPORTED`, **arrêter et remonter au décideur**.

## Travail — partie D : contrat `RouterDriver`

`src/drivers/__init__.py` et `src/drivers/_base.py`. Aucun import vendor au
niveau module (invariant C1).

```python
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

class RouterRole(str, Enum):
    PRIMARY = "primary"   # scoring + reboot automatique (USG, comportement actuel)
    BACKUP = "backup"     # management + audit, JAMAIS de reboot automatique

class Readiness(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"   # info indisponible — n'est PAS un état sain

class Hop(str, Enum):
    """Saut du chemin d'audit — sert à attribuer une panne au bon endroit."""
    BRIDGE = "bridge"     # le Pi Zero
    WIRELESS = "wireless" # le saut WiFi Pi Zero <-> MR110
    DEVICE = "device"     # le routeur lui-meme
    ROUTE = "route"       # defaut de configuration du chemin (C8), pas une panne

@dataclass(frozen=True)
class RouterHealth:
    reachable: bool
    internet_ok: bool
    rtt_ms: float | None = None
    failed_hop: Hop | None = None   # None si tout repond
    detail: str = ""

@dataclass(frozen=True)
class RouterReadiness:
    state: Readiness = Readiness.UNKNOWN
    reasons: tuple[str, ...] = ()   # ex: ("rsrp=-118 < seuil -110",)

@dataclass(frozen=True)
class RouterMetrics:
    """Toutes les valeurs nullable : dependantes du vendor et du firmware."""
    cpu_usage: float | None = None
    mem_usage: float | None = None
    wan_ip: str | None = None
    clients_total: int | None = None
    # --- specifique 4G/LTE ---
    network_type: str | None = None
    sim_status: str | None = None
    signal_bars: int | None = None
    rsrp: int | None = None
    rsrq: int | None = None
    snr: int | None = None
    isp_name: str | None = None
    data_used_bytes: int | None = None
    rx_speed_bps: int | None = None
    tx_speed_bps: int | None = None

class RouterDriver(Protocol):
    vendor: str                                       # "usg" | "tplink"
    def health(self) -> RouterHealth: ...             # never raise
    def metrics(self) -> RouterMetrics: ...           # never raise -> None si indispo
    def readiness(self) -> RouterReadiness: ...       # never raise -> UNKNOWN si indispo
    def reboot(self) -> bool: ...                     # never raise
    def test_connection(self) -> bool: ...            # diagnostic
```

`failed_hop` est le champ qui rend les alertes exploitables : « secours
injoignable » sans dire **où** oblige à tout re-diagnostiquer à la main.

> `UsgDriver` n'est **pas** implémenté dans cette phase : l'extraction de l'USG
> derrière ce contrat appartient à la phase B (moteur multi-cible). Le contrat
> est posé maintenant pour que `TplinkDriver` ait la bonne forme dès le départ.

## Tests

`tests/test_drivers_base.py` :
- Un driver factice implémentant le Protocol est accepté (structural typing).
- Les dataclasses sont `frozen` (mutation → `FrozenInstanceError`).
- Défauts conservateurs : `Readiness.UNKNOWN`, champs métriques `None`,
  `failed_hop=None`.
- `python -c "import drivers"` réussit sans `tplinkrouterc6u` installé.

Le script de spike n'est pas testé unitairement (jetable, I/O matériel) ; il doit
être exclu de la couverture et ne pas casser le lint.

## Critères d'acceptation

- [ ] Depuis un hôte watchdog de Dijon : ping du Pi Zero, ping du MR110 et accès
      HTTP à son admin — tous OK
- [ ] IP forwarding + NAT persistants au reboot du Pi Zero
- [ ] Route posée **uniquement** sur les hôtes watchdog (ni USG, ni DHCP)
- [ ] `docs/runbooks/pi-zero-mr110-access.md` écrit, rejoué avec succès sur Nice
- [ ] **Rien installé sur le Pi Zero** (ni Python, ni lib)
- [ ] `scripts/spike_tplink.py` exécuté **depuis un hôte watchdog** ; `logout()`
      garanti ; ni reboot ni SMS déclenchés par défaut
- [ ] `docs/spikes/2026-08-XX-mr110-compat.md` : verdict, **révision matérielle
      et firmware relevés par site**, tableau des champs, **tableau des commandes
      disponibles**, version de lib retenue, plan B si non-`FULL`
- [ ] `src/drivers/_base.py` créé (tous types frozen, `Hop` inclus)
- [ ] `tests/test_drivers_base.py` vert
- [ ] `python -c "import watchdog"` et `python -c "import drivers"` verts **sans** la lib
- [ ] Suite existante toujours verte, coverage ≥ 80 %
- [ ] Aucun mot de passe dans les logs, le rapport, ou le runbook

## Frontières de fichiers

- **Créer** : `src/drivers/__init__.py`, `src/drivers/_base.py`,
  `scripts/spike_tplink.py`, `docs/spikes/2026-08-XX-mr110-compat.md`,
  `docs/runbooks/pi-zero-mr110-access.md`, `tests/test_drivers_base.py`
- **Modifier** : aucun fichier source existant
- **Lecture seule** : `src/usg.py`, `src/connectivity.py` (référence de style)
- **Hors dépôt** : configuration réseau des Pi Zero et des hôtes watchdog —
  documentée dans le runbook, pas versionnée
- **Contrats partagés** : `_base.py` est consommé par tous les sprints suivants
  et par la phase B — toute évolution est un changement d'interface à signaler
