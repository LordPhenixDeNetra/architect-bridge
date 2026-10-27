# ARCHITECT Bridge - Sous-projet A : reception des resultats

Date : 2026-10-27
Statut : en revue

## 1. Objectif

Un service Python, installe sur le reseau local de l'hopital, recoit les resultats
envoyes par l'automate Abbott ARCHITECT (protocole ASTM E1381/E1394) et les expose
via une API REST. Le backend Spring Boot Hopitalia (deploye sur un serveur local de
l'hopital) interroge cette API et integre les resultats dans ses tables laboratoire.

Critere de succes : un resultat valide sur l'ARCHITECT apparait dans Hopitalia sans
ressaisie, et aucun resultat n'est perdu, meme si Spring ou le reseau est indisponible.

Reference protocole : *Abbott Standard Interface RS-232 Manual, ARCHITECT i System*,
91407-103 (2000). Une revision plus recente (91407-109) existe ; la version adaptee au
logiciel installe sur l'automate doit etre obtenue aupres d'Abbott avant la mise en
production.

## 2. Perimetre

Inclus (sous-projet A) :
- Reception unidirectionnelle : automate -> service.
- Resultats patients, resultats de controle qualite, exceptions (test non realise).
- Journal brut de tous les messages, rejouable.
- API REST de lecture et d'acquittement.
- Simulateur ARCHITECT pour les tests.

Exclus (sous-projets ulterieurs) :
- B : envoi de demandes d'analyses et mode requete (Query).
- C : supervision avancee, tableau de bord CQ.
- Correspondance code test ARCHITECT -> S_ACTE Hopitalia et quarantaine : faites cote
  Spring (tache separee dans hopitalia-backend).
- Unicode 16 bits (non supporte par l'ARCHITECT au lancement ; page de code 850).

## 3. Decisions

| # | Decision | Raison |
|---|---|---|
| D1 | Commencer par le sous-projet A | 80 % de la valeur, besoin reel du labo pas encore clarifie |
| D2 | Spring interroge Python (pull) sur le LAN | Hopitalia et l'automate sont sur le meme reseau local |
| D3 | Python reste generique, Spring fait la correspondance | Un meme service pour tous les hopitaux ; pas de duplication du referentiel S_ACTE |
| D4 | Un seul processus : thread connecteur (pyserial est bloquant) + FastAPI/uvicorn | Un seul service a installer ; etat de la liaison en memoire pour /health |
| D5 | Couche ASTM ecrite en interne (pas la lib `astm` PyPI) | ~300 lignes testables, adaptees aux specificites ARCHITECT |

## 4. Architecture

```
            +---------------- Service Python (1 processus) ----------------+
ARCHITECT --| transport -> datalink -> codec -> drivers/architect           |
 (COM/TCP)  | (serial|tcp)  (E1381)    (E1394)        |                     |
            |                                         v                     |
            |                               store (SQLite WAL)              |
            |                                         ^                     |
            |                                api (FastAPI) <-------------- |-- Spring Hopitalia
            +---------------------------------------------------------------+
```

Arborescence :

```
architect-bridge/
  bridge/
    transport/serial.py, transport/tcp.py
    datalink.py
    codec.py
    drivers/architect.py
    store.py
    api.py
    config.py
    main.py
  simulator/
  tests/
  config.example.toml
```

| Module | Responsabilite | Depend de |
|---|---|---|
| transport | Ouvrir le port serie ou la socket TCP ; lire/ecrire des octets. Interface commune `read(timeout)` / `write(bytes)` | pyserial, socket |
| datalink | Machine a etats E1381 : ENQ/ACK/NAK/EOT, assemblage des trames ETB/ETX, checksum, numero de trame, timeouts. Produit un message complet (texte) | transport (interface) |
| codec | `message -> [Record]` et `[Record] -> message` ; delimiteurs lus dans l'en-tete H (`|\^&`) ; aucune connaissance ARCHITECT | rien |
| drivers/architect | `[Record] -> [Result]` : hierarchie P/O/R/C, types F/I/P, drapeaux, exceptions (O.26 = X), CQ (O.12 = Q) | codec |
| store | Journal brut, resultats, curseur, purge | sqlite3 |
| api | Endpoints REST | store, etat liaison en memoire |

Flux d'un message :
1. L'automate envoie ENQ ; datalink repond ACK, recoit et verifie les trames. Chaque
   enregistrement ASTM est transmis dans une ou plusieurs trames (ETB...ETB, ETX) ; une
   session ENQ...EOT peut contenir plusieurs messages H...L.
2. A la trame qui termine l'enregistrement L, le message complet est ecrit dans
   `raw_messages`, PUIS ACK est envoye. Si l'ecriture echoue, NAK : l'automate conserve
   et renverra le message. Si EOT arrive alors qu'un message est commence sans L, les
   enregistrements deja acquittes sont tout de meme ecrits (ils seront en `parse_error`).
3. codec + driver interpretent le message. Succes : lignes dans `results`. Echec :
   `raw_messages.status = parse_error` avec l'erreur ; le message reste rejouable.
4. Spring lit `GET /results?after=N`, enregistre, puis `POST /results/ack`.

Regle : l'interpretation n'intervient jamais dans la decision ACK/NAK. Seuls le
checksum, le numero de trame et l'ecriture du journal brut la conditionnent.

## 5. Modele de donnees (SQLite, mode WAL)

### raw_messages
| Colonne | Type | Contenu |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| received_at | TEXT (ISO 8601 UTC) | |
| text | TEXT | Message complet H...L, enregistrements separes par CR |
| status | TEXT | `received`, `parsed`, `parse_error` |
| error | TEXT NULL | Message d'erreur d'interpretation |

### results
| Colonne | Source ASTM | Note |
|---|---|---|
| seq | - | INTEGER PK AUTOINCREMENT ; curseur lu par Spring |
| uid | - | UNIQUE : `instrument_serial|specimen_id|assay_number|result_type|completed_at` |
| raw_message_id | - | FK raw_messages.id |
| kind | O.12, O.26 | `patient`, `control`, `exception` |
| specimen_id | O.3 | |
| instrument_specimen_id, carrier_id, position | O.4 | |
| patient_id_practice, patient_id_lab, patient_id_3 | P.3, P.4, P.5 | |
| assay_number, assay_name, dilution, assay_status | R.3 (ou O.5 pour une exception) | |
| reagent_lot, reagent_serial, control_lot | R.3 | |
| result_type | R.3 | `F`, `I`, `P` ; NULL pour une exception |
| value | R.4 | Chaine telle que recue (`<1.20`, `NEGATIVE`...) |
| units | R.5 | |
| reference_range | R.6 | |
| flags | R.7 | Tableau JSON, ex. `["HIGH"]`, `["1-2s"]` |
| result_status | R.9 | `F` ou `R` |
| operator_order, operator_release | R.11 | |
| completed_at | R.13 | ISO 8601 |
| instrument_serial | R.14 | Pour une exception : numero de serie du SCC (H.5) |
| priority | O.6 | `S` ou `R` |
| comments | C.4 | Tableau JSON des commentaires qui suivent R (ou O pour une exception) |

Pour une exception (sans enregistrement R), `uid` utilise `result_type = X` et
`completed_at` = date/heure de l'en-tete H (H.14).

Insertion : `INSERT ... ON CONFLICT(uid) DO NOTHING` (idempotent, y compris au rejeu).

### api_cursor
Une ligne : `acked_seq INTEGER`.

### Donnees personnelles
Le nom, la date de naissance et le sexe du patient (P.6, P.8, P.9) ne sont pas
stockes. Spring rattache le resultat au patient via le SID.

### Purge
Tache quotidienne : supprimer les `results` avec `seq <= acked_seq` et plus anciens que
`retention_days` (defaut 90), puis les `raw_messages` plus anciens que `retention_days`
qui ne sont plus references.

## 6. API REST

Toutes les requetes exigent l'en-tete `X-API-Key` ; sinon `401`.

| Methode | Chemin | Description |
|---|---|---|
| GET | `/results?after={seq}&limit={n}` | Resultats avec `seq > after`, tries par seq ; `limit` defaut 100, max 1000. Reponse `{ "items": [...], "lastSeq": <seq du dernier item ou after> }` |
| POST | `/results/ack` | Corps `{ "upToSeq": n }`. Met a jour `acked_seq` (jamais en arriere). Reponse `204` |
| GET | `/health` | `{ "connected", "transport", "lastFrameAt", "lastMessageAt", "messagesToday", "parseErrors", "unackedResults", "version" }` |
| GET | `/raw-messages?status={status}&limit={n}` | Messages bruts, pour diagnostic |
| POST | `/raw-messages/{id}/replay` | Reinterprete un message brut ; renvoie le nombre de resultats inseres |

Exemple d'item :

```json
{
  "seq": 1042,
  "uid": "I20100|SID13|0241|F|1999-07-15T08:10:30",
  "kind": "patient",
  "specimenId": "SID13",
  "instrumentSpecimenId": "SID13", "carrierId": "A123", "position": 5,
  "patientIds": { "practice": null, "lab": null, "id3": "PIDSID13" },
  "assay": { "number": "0241", "name": "TSH", "dilution": "UNDILUTED", "status": "P" },
  "reagent": { "lot": "0607M200", "serial": "01824" }, "controlLot": null,
  "resultType": "F",
  "value": "4.6011", "units": "mIU/mL", "referenceRange": "4.292500 TO 5.397300",
  "flags": [],
  "resultStatus": "F",
  "operators": { "order": "ECB", "release": "RY" },
  "completedAt": "1999-07-15T08:10:30",
  "instrumentSerial": "I20100",
  "priority": "R",
  "comments": [],
  "rawMessageId": 311
}
```

Contrat de consommation cote Spring (hors perimetre, a titre de reference) :
toutes les 15 s, lire `GET /results?after=<curseur Spring>`, enregistrer chaque item de
facon idempotente (cle `uid`) et le nouveau curseur dans la meme transaction, puis
`POST /results/ack`. Spring est maitre de son curseur ; l'ack sert a la supervision et
a la purge.

Securite :
- Adresse d'ecoute configurable ; defaut `127.0.0.1`. Jamais `0.0.0.0` par defaut.
- Pas de HTTPS dans A (LAN, donnees pseudonymisees). Ajout possible via reverse proxy.
- Aucun endpoint ne permet d'envoyer des donnees a l'automate.

## 7. Couche liaison (E1381) - parametres

| Parametre | Valeur |
|---|---|
| Serie par defaut | 9600 bauds, 8 bits, sans parite, 1 stop (configurable) |
| Taille max trame | 240 caracteres de donnees |
| Numero de trame | 1..7 puis 0 ; trame dupliquee (meme numero que la precedente acceptee) : ACK sans la reprendre ; numero inattendu : NAK |
| Checksum | somme modulo 256 de FN a ETB/ETX inclus, 2 caracteres hexa majuscules |
| Timeout reception entre trames | 30 s -> abandon du message, retour au repos |
| Contention | en A le service n'emet jamais ENQ ; pas de contention |
| Encodage | cp850 |
| TCP | le service ecoute (mode serveur) sur hote/port configures ; l'automate (ou le simulateur) se connecte |

## 8. Gestion des erreurs

| Situation | Reaction |
|---|---|
| Checksum ou numero de trame invalide | NAK ; log WARN |
| Timeout 30 s en cours de message | Abandon du message partiel ; log WARN ; repos |
| Port absent / deconnecte | Nouvelle tentative toutes les 5 s ; `/health.connected = false` |
| Echec d'interpretation | `parse_error` + compteur ; message rejouable |
| Resultat en double | Ignore via `uid` |
| Echec d'ecriture SQLite du message brut | NAK sur la trame finale ; log ERREUR ; remonte dans `/health` |

Logs : `logging` + `RotatingFileHandler`, prefixes `[INFO]`, `[WARN]`, `[ERREUR]`, sans
emoji.

## 9. Tests

- Unitaires :
  - checksum : `1ABCDEFGHI<ETX>` -> `A1` (manuel p. 1-22) ;
  - datalink : assemblage ETB/ETX, numero de trame 7 -> 0, trame dupliquee, NAK sur
    mauvais checksum, timeout ;
  - codec : delimiteurs, repetitions, composants vides ;
  - driver : exemples du manuel section 4 (B-hCG F/I/P, TSH, controle Q, exception X).
- Datalink : transport factice en memoire injectant les cas d'erreur.
- Bout en bout : simulateur en TCP local -> service -> `GET /results` -> JSON attendu.
- Validation sur site : ecoute du flux reel, comparaison de 20 resultats avec l'ecran de
  l'automate ; les messages reels captures rejoignent les jeux de tests.

## 10. Deploiement

- Python >= 3.11 ; dependances : `fastapi`, `uvicorn`, `pyserial`.
- `config.toml` (lu par `tomllib`) : transport, port, vitesse, parite, bits, stop, hote
  et port TCP, chemin SQLite, cle API, adresse et port d'ecoute, `retention_days`.
- Windows : service via NSSM (demarrage automatique, redemarrage sur crash).
- Linux : unite systemd, ou conteneur Docker avec `--device` pour le port serie.

## 11. Questions ouvertes (n'impactent pas A)

- Modele exact et version logicielle de l'ARCHITECT ; obtenir le manuel ASI correspondant.
- Liaison physique : RS-232 (COM5/P3) ou TCP/IP.
- Identifiant colle sur le tube (numero d'entree Hopitalia ou autre) : determine la
  correspondance cote Spring.
- Mode configure sur l'automate : `Communications = On` requis ; `Approved QC results`
  a activer si le CQ doit remonter.
