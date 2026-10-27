# Installation d'ARCHITECT Bridge

Ce document aide a choisir comment installer le service selon le materiel disponible au
laboratoire, puis detaille l'installation sur un PC Windows (cas le plus courant).

## Contrainte de depart

Un cable RS-232 ne depasse guere 15 metres. Le service doit donc tourner **sur une machine placee
a cote de l'automate**, sauf si les donnees de l'automate arrivent par le reseau (port TCP/IP de
l'automate ou convertisseur serie-Ethernet).

Docker Desktop sous Windows **ne transmet pas les ports COM** aux conteneurs : sur un PC Windows
relie en RS-232, le service s'installe donc sans Docker.

## Choisir une option

| Option | Materiel | Docker | Avis |
|---|---|---|---|
| 1. Service Windows natif (NSSM) | PC Windows du labo relie a l'automate | Non | Recommande si le PC est sous Windows : le plus simple et le plus fiable |
| 2. Petit PC Linux a cote de l'automate | Mini-PC ou Raspberry Pi sous Linux + adaptateur USB-serie | Oui (`devices: /dev/ttyUSB0`) | Recommande pour tout gerer en conteneurs |
| 3. Convertisseur serie-Ethernet | Boitier type Moxa NPort / USR-TCP232 branche sur l'automate et le reseau | Oui, n'importe ou (mode TCP) | Le service peut tourner sur le serveur Hopitalia, sans cable jusqu'a lui |
| 4. usbipd-win + WSL2 | PC Windows | Oui, avec Docker installe dans WSL (pas Docker Desktop) | Deconseille : l'USB doit etre re-attache a chaque redemarrage |

A verifier sur l'automate (*System > Configuration*) : les ARCHITECT recents (i1000SR, i2000SR,
ci4100) disposent souvent d'un port TCP/IP integre. Dans ce cas, l'option 3 ne demande aucun
convertisseur.

Regle simple :
- PC a cote de l'automate sous Windows -> **option 1** ;
- preference pour Docker partout -> **option 2 ou 3** (voir la section Docker du [README](../README.md)).

## Option 1 : installation sur le PC Windows du labo

### Prerequis

- Python 3.11 ou plus recent ([python.org](https://www.python.org)), case "Add to PATH" cochee.
- [NSSM](https://nssm.cc/download) : decompresser `nssm.exe`, par exemple dans `C:\nssm\`.
- Git, ou a defaut l'archive ZIP du depot.

### Etapes

Dans PowerShell **lance en administrateur** :

```powershell
# 1. Recuperer le code
cd C:\
git clone https://github.com/LordPhenixDeNetra/architect-bridge.git
cd C:\architect-bridge

# 2. Environnement Python et installation
python -m venv .venv
.venv\Scripts\pip install .

# 3. Configuration
copy config.example.toml config.toml
notepad config.toml
```

Dans `config.toml`, regler au minimum :

| Cle | Valeur |
|---|---|
| `[link] port` | Port COM de l'adaptateur USB-serie (*Gestionnaire de peripheriques > Ports (COM et LPT)*) |
| `[api] api_key` | Cle longue et secrete, identique a `ARCHITECT_BRIDGE_API_KEY` cote Hopitalia |
| `[api] host` | IP reseau du PC (ex. `192.168.1.30`) pour que le serveur Hopitalia puisse le joindre |

```powershell
# 4. Tester a la main (Ctrl+C pour arreter)
.venv\Scripts\architect-bridge --config C:\architect-bridge\config.toml

# 5. Installer en service Windows (demarrage automatique, relance en cas de plantage)
C:\nssm\nssm.exe install ArchitectBridge C:\architect-bridge\.venv\Scripts\architect-bridge.exe --config C:\architect-bridge\config.toml
C:\nssm\nssm.exe set ArchitectBridge AppDirectory C:\architect-bridge
C:\nssm\nssm.exe set ArchitectBridge Start SERVICE_AUTO_START
C:\nssm\nssm.exe start ArchitectBridge

# 6. Ouvrir le port de l'API dans le pare-feu, uniquement pour le serveur Hopitalia
New-NetFirewallRule -DisplayName "ArchitectBridge API" -Direction Inbound -Protocol TCP -LocalPort 8085 -RemoteAddress <IP_serveur_Hopitalia> -Action Allow
```

### Verification

Depuis le serveur Hopitalia :

```bash
curl -H "X-API-Key: <cle>" http://192.168.1.30:8085/health
```

La reponse doit contenir `"connected": true` une fois l'automate branche et configure
(*Host - release mode > Communications = On*, voir le [README](../README.md)).

Cote Hopitalia, renseigner ensuite :

```
ARCHITECT_BRIDGE_URL=http://192.168.1.30:8085
ARCHITECT_BRIDGE_API_KEY=<cle>
```

et passer `architect.bridge.enabled: true` dans le profil de l'hopital concerne.

### Exploitation

| Action | Commande |
|---|---|
| Consulter les logs | `C:\architect-bridge\logs\bridge.log` |
| Redemarrer le service | `C:\nssm\nssm.exe restart ArchitectBridge` |
| Arreter le service | `C:\nssm\nssm.exe stop ArchitectBridge` |
| Mettre a jour | `git pull`, puis `.venv\Scripts\pip install .`, puis `nssm restart ArchitectBridge` |
| Desinstaller le service | `C:\nssm\nssm.exe remove ArchitectBridge confirm` |

La base `architect-bridge.db` (journal brut et resultats) se trouve dans `C:\architect-bridge\` :
la conserver lors des mises a jour.
