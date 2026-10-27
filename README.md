# ARCHITECT Bridge

Passerelle entre l'automate d'immunoanalyse **Abbott ARCHITECT** et le backend **Hopitalia**.

Le service recoit les resultats envoyes par l'automate (protocole ASTM E1381 / E1394, interface
ASI d'Abbott), les conserve sans perte dans une base SQLite locale et les expose via une API REST
que Hopitalia (Spring Boot) interroge.

```
ARCHITECT --RS-232 / TCP--> ARCHITECT Bridge (SQLite) <--REST-- Hopitalia
```

Perimetre actuel (sous-projet A) : reception des resultats patients, des controles qualite et des
exceptions. L'envoi de demandes vers l'automate n'est pas encore pris en charge.

Documents de conception : [specification](docs/superpowers/specs/2026-10-27-architect-bridge-a-design.md),
[plan](docs/superpowers/plans/2026-10-27-architect-bridge-a.md).

## Installation

Quelle installation choisir selon le materiel du labo (Windows, Linux, Docker, convertisseur
serie-Ethernet) : voir [docs/INSTALLATION.md](docs/INSTALLATION.md).

Prerequis : Python 3.11 ou plus recent.

```bash
python -m venv .venv
.venv\Scripts\pip install -e .          # Windows
# .venv/bin/pip install -e .            # Linux
```

Pour le developpement : `pip install -e ".[dev]"` puis `pytest`.

## Configuration

```bash
copy config.example.toml config.toml    # Windows (cp sous Linux)
```

Renseigner au minimum `[api] api_key` (cle partagee avec Hopitalia) et `[link] port`
(port COM du PC). Toutes les cles sont commentees dans [config.example.toml](config.example.toml).

## Lancement

```bash
.venv\Scripts\architect-bridge --config config.toml
```

- API : `http://127.0.0.1:8085` (documentation interactive : `/docs`)
- Logs : `logs/bridge.log` (rotation automatique)

## Reglages sur l'ARCHITECT

Menu *System > Configuration* (administrateur) :

| Ecran | Reglage |
|---|---|
| Host - release mode > Communications | `On` |
| Host - release mode > Transmit to host | `Approved patient results` : Collated ou Single ; `Approved QC results` : On si le CQ doit remonter |
| Serial ports | Port `COM5 (LIS)` connecteur P3, 9600 bauds, parite None, 8 bits, 1 stop (identique a `config.toml`) |

## Cablage RS-232

L'ARCHITECT est cable en DTE. Avec un PC (DTE), il faut un cable croise (null-modem) :

| ARCHITECT (DB-25) | PC (DB-9) |
|---|---|
| 2 (emission) | 2 (reception) |
| 3 (reception) | 3 (emission) |
| 7 (masse) | 5 (masse) |
| 1 (blindage) | non connecte |

Un adaptateur USB-serie (puce FTDI de preference) convient.

## Installation en service

**Windows** avec [NSSM](https://nssm.cc) :

```bash
nssm install ArchitectBridge "C:\chemin\vers\.venv\Scripts\architect-bridge.exe" --config "C:\chemin\vers\config.toml"
nssm set ArchitectBridge AppDirectory "C:\chemin\vers\architect-bridge"
nssm start ArchitectBridge
```

**Linux** avec systemd (`/etc/systemd/system/architect-bridge.service`) :

```ini
[Unit]
Description=ARCHITECT Bridge
After=network.target

[Service]
WorkingDirectory=/opt/architect-bridge
ExecStart=/opt/architect-bridge/.venv/bin/architect-bridge --config /opt/architect-bridge/config.toml
Restart=always

[Install]
WantedBy=multi-user.target
```

Puis `systemctl enable --now architect-bridge`.

## Docker

```bash
cp config.docker.example.toml config.toml   # renseigner api_key, transport, port
docker compose up -d --build
docker compose logs -f architect-bridge
```

- La base SQLite et les logs sont dans le volume `bridge-data` (`/data` dans le conteneur) : ils
  survivent aux redemarrages et aux mises a jour de l'image.
- **Port serie : hote Linux uniquement.** Decommenter `devices` dans `docker-compose.yml`
  (`/dev/ttyUSB0`) et garder `port = "/dev/ttyUSB0"` dans `config.toml`. Docker Desktop sous Windows
  ne transmet pas les ports COM : sur un PC Windows relie en RS-232, utiliser l'installation en
  service NSSM ci-dessus.
- **Mode TCP** : `transport = "tcp"` et decommenter `"5100:5100"`. Renseigner `tcp_allowed_peer`
  avec l'adresse vue par le conteneur (avec le reseau bridge de Docker, l'automate peut apparaitre
  sous l'IP de la passerelle Docker : verifier dans les logs `[WARN] Connexion refusee depuis ...`).
- **API** : publiee par defaut sur `127.0.0.1:8085` uniquement. Si Hopitalia tourne sur un autre
  serveur, remplacer par l'IP LAN (`"192.168.x.y:8085:8085"`).
- **Hopitalia dans Docker sur la meme machine** : `127.0.0.1` designe alors le conteneur Hopitalia
  lui-meme. Mettre les deux conteneurs sur le meme reseau Docker et utiliser
  `ARCHITECT_BRIDGE_URL=http://architect-bridge:8085` :

  ```yaml
  # docker-compose.yml du bridge
  services:
    architect-bridge:
      networks: [hopitalia]
  networks:
    hopitalia:
      external: true
      name: <reseau du compose Hopitalia>   # voir `docker network ls`
  ```

Test sans automate : `transport = "tcp"`, port 5100 publie, puis depuis l'hote
`python -m simulator.architect_sim --port 5100` et
`curl -H "X-API-Key: <cle>" http://127.0.0.1:8085/results`.

## API REST

Toutes les requetes exigent l'en-tete `X-API-Key`.

| Methode | Chemin | Role |
|---|---|---|
| GET | `/results?after={seq}&limit={n}` | Resultats avec `seq > after` (100 par defaut, 1000 max). Reponse `{ "items": [...], "lastSeq": n }` |
| POST | `/results/ack` | Corps `{ "upToSeq": n }` : confirme la reception jusqu'a `n` |
| GET | `/health` | Etat de la liaison, compteurs, version |
| GET | `/raw-messages?status=parse_error` | Messages bruts (diagnostic) |
| POST | `/raw-messages/{id}/replay` | Reinterprete un message brut |

Chaque test produit jusqu'a trois resultats, distingues par `resultType` : `F` (valeur finale),
`I` (interpretation qualitative), `P` (reponse brute en RLU). Un test non realise arrive avec
`kind = "exception"`, `resultType = "X"` et la raison dans `comments`. La valeur est toujours une
chaine (`"<1.20"`, `"NEGATIVE"`...).

### Contrat de consommation cote Hopitalia

Toutes les 15 secondes :

1. `GET /results?after=<dernier seq enregistre par Hopitalia>`
2. Enregistrer chaque item de facon idempotente (cle unique : `uid`) et le nouveau curseur dans la
   meme transaction.
3. `POST /results/ack` avec `upToSeq = lastSeq`.

Hopitalia est maitre de son curseur : en cas d'arret, il reprend la ou il s'etait arrete, sans
doublon. La correspondance entre le code de test ARCHITECT (`assay.number`) et les actes Hopitalia
est geree cote Hopitalia.

## Tester sans automate

Le simulateur joue le role de l'ARCHITECT en TCP :

1. Dans `config.toml` : `transport = "tcp"`, `tcp_host = "127.0.0.1"`, `tcp_port = 5100`.
   En production en mode TCP, renseigner `tcp_allowed_peer` avec l'adresse IP de l'automate.
2. Lancer le service, puis dans un autre terminal :

```bash
.venv\Scripts\python -m simulator.architect_sim --port 5100
curl -H "X-API-Key: <cle>" http://127.0.0.1:8085/results
```

Le simulateur peut aussi rejouer des messages captures sur site :
`--file messages.txt` (un enregistrement par ligne, messages separes par une ligne vide).

## Depannage

| Symptome | Verification |
|---|---|
| `/health` indique `connected: false` | Champ `error` ; port COM, cable, alimentation de l'automate |
| Aucun message recu | Reglage `Communications = On` sur l'automate ; parametres serie identiques des deux cotes |
| `parseErrors` augmente | `GET /raw-messages?status=parse_error`, corriger puis `POST /raw-messages/{id}/replay` |
| `unackedResults` augmente | Hopitalia n'interroge plus l'API (verifier son planificateur et la cle) |
