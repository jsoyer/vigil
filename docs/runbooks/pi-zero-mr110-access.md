# Runbook — Accès aux TL-MR110 (lignes de secours 4G)

Mis à jour d'après le terrain le 2026-08-23 (spike FULL, cf.
`docs/spikes/2026-08-23-mr110-compat.md`).

## Topologie réelle

Pas de Pi Zero pont dédié : **les guardians (instances Vigil slave) portent
le lien vers le MR110 de leur site**.

| Site | Hôte d'accès | Login SSH | MR110 (admin HTTP) | Sous-réseau |
|---|---|---|---|---|
| Dijon | `bbh-dij-guardian` | `dietpi` (clé fleet) | `http://192.168.10.1` | 192.168.10.0/24 |
| Nice | `bbh-nce-guardian` | `dietpi` (clé fleet) | `http://192.168.30.1` | 192.168.30.0/24 |

Les **masters** (bbh-network, penelope) n'ont **pas de route** vers ces
sous-réseaux (vérifié) : pour eux le mode C16 est `remote` (passage par le
guardian). Pour les guardians eux-mêmes : `bridged` (accès direct).

## Secrets

Mots de passe admin des MR110 : dans le `.env` de chaque instance concernée
(`TPLINK_0_PASSWORD`, chmod 600 root) — **jamais** en argument CLI, jamais
dans un dépôt, jamais loggés. Le script de spike ne les accepte que via la
variable d'environnement `TPLINK_PASSWORD`.

## Vérifier l'accès (procédure rejouable)

Depuis le guardian du site :

```bash
ping -c2 192.168.10.1            # (Dijon ; 192.168.30.1 a Nice)
curl -sI --max-time 5 http://192.168.10.1/ | head -1   # HTTP/1.1 405 = UI vivante
```

Depuis un master (contre-vérification du mode remote) :

```bash
ping -c2 -W2 192.168.10.1        # doit ECHOUER (pas de route)
```

## Rejouer le spike de compatibilité

```bash
# Sur le guardian :
python3 -m venv /tmp/spike-venv
/tmp/spike-venv/bin/pip install -q tplinkrouterc6u
IFS= read -rs TPLINK_PASSWORD    # coller le mdp, Entree
export TPLINK_PASSWORD
/tmp/spike-venv/bin/python ~/github/vigil/scripts/spike_tplink.py \
    --host 192.168.10.1 --mode bridged --json-out ~/spike-mr110.json
```

Verdict attendu : `FULL` avec `tplinkrouterc6u==5.31.1`. Un verdict différent
après un changement de firmware MR110 doit être traité comme une régression
(re-consulter le tableau des commandes du rapport).

## Ce que ce chemin n'est PAS

- Pas de NAT/route à poser sur les LAN des sites : l'accès MR110 reste
  confiné aux guardians (surface d'attaque minimale).
- Aucune action automatique du watchdog sur ces équipements (rôle `BACKUP`,
  C6) : uniquement du management à la demande, avec confirmation.
