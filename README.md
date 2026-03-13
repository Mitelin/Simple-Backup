# Simple Backup

Simple Backup je jednoduchy backup framework pro Linux server. Aplikace funguje jako orchestrator, ktery automaticky najde uzivatelske shell joby, spusti je, prevezme jejich vystupy a ulozi je do jednoho finalniho backup souboru.

## Cile projektu

- jednoducha instalace a provoz na serveru
- minimalni globalni konfigurace
- automaticke hledani job skriptu ve slozce `jobs/`
- modularni pristup bez nutnosti registrovat joby v konfiguraci
- finalni vystup vzdy jako jeden archivovany soubor
- zaklad pro retention, logovani a pozdejsi rozsireni

## Navrhovany princip

Framework bude resit:

- nacteni konfigurace
- discovery spustitelnych `.sh` jobu
- spousteni jobu s predanym runtime kontextem
- prevzeti vystupnich souboru z pracovni slozky
- zabaleni vsech vystupu a logu do jednoho finalniho souboru
- ulozeni finalniho souboru do storage
- mount safety kontrolu
- jednoduchy logging a retention politiku

Job samotny resi konkretni backup logiku, napr. SQL dump nebo export souboru.

## Pravidlo finalni zalohy

Kazdy beh vytvori prave jeden finalni backup soubor.

- obsahuje log z behu
- obsahuje vsechny jednotlive vystupy vytvorene joby
- ma jasne casove razitko v nazvu
- pouziva nazev zarizeni, ktery se defaultne vezme z hostname
- nazev zarizeni lze zmenit v konfiguraci

Priklad vystupu:

```text
my-server-20260313T221500Z.tar.gz
```

## Ocekavane pouziti

1. upravit globalni `config.yaml`
2. vlozit vlastni shell skripty do `jobs/`
3. nastavit jim executable prava
4. spustit orchestrator

## Rychly start

Minimalni lokalni setup pro vyvoj nebo prvni test:

```text
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
copy config.example.yaml config.yaml
```

Pak vytvorit nebo zkopirovat prvni job do `jobs/` a spustit:

```text
simple-backup run --config config.yaml
```

Na Linux serveru bude typicky postup stejny, jen s aktivaci virtualenv podle shellu.

## Struktura projektu

```text
Simple Backup/
|- config.example.yaml
|- jobs/
|- examples/jobs/
|- src/simple_backup/
`- tests/
```

Vyznam hlavnich slozek:

- `jobs/` obsahuje realne produkcni `.sh` joby, ktere se maji spoustet
- `examples/jobs/` obsahuje pouze sablony a nespousti se automaticky
- `src/simple_backup/` obsahuje orchestrator, konfiguraci a pomocne moduly
- `tests/` obsahuje automaticke testy projektu

## Predbezny config

```yaml
device:
  name: myserver

storage:
  target_root: /mnt/nas/backups/myserver
  require_mount: true

retention:
  daily: 7
  weekly: 4
  monthly: 12
  yearly: 10

runtime:
  jobs_dir: ./jobs
  work_dir: ./tmp
  log_dir: ./logs
  job_timeout_seconds: 3600

notifications:
  email:
    enabled: false
    smtp_host: smtp.example.com
    smtp_port: 587
    smtp_username: backup@example.com
    smtp_password: change-me
    smtp_from: backup@example.com
    smtp_to:
      - admin@example.com
    use_starttls: true
    use_ssl: false
    subject_prefix: "[Simple Backup]"
```

## Konfigurace

Sekce `device`:

- `name` je jmeno stroje pouzite v nazvu vysledneho archivu
- pokud chybi, vezme se automaticky hostname stroje

Sekce `storage`:

- `target_root` je cilovy adresar pro finalni `.tar.gz` backupy
- `require_mount` vynuti kontrolu, ze cil je opravdu mounted storage

Sekce `retention`:

- `daily` pocet unikatnich denich bucketu, ktere se maji ponechat
- `weekly` pocet tydennich bucketu
- `monthly` pocet mesicnich bucketu
- `yearly` pocet rocnich bucketu, `0` znamena bez rocni vrstvy

Sekce `runtime`:

- `jobs_dir` slozka s realnymi job scripti
- `work_dir` docasny pracovni adresar pro artefakty jednoho behu
- `log_dir` adresar s logy jednotlivych behu
- `job_timeout_seconds` timeout pro jeden job script

Sekce `notifications.email`:

- `enabled` zapina nebo vypina email alerty
- `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password` urcuji SMTP spojeni
- `smtp_from` je odesilatel
- `smtp_to` je seznam prijemcu
- `use_starttls` zapne STARTTLS nad beznym SMTP spojenim
- `use_ssl` pouzije SMTPS spojeni od zacatku
- `subject_prefix` prida prefix do predmetu alert emailu

## Aktualni stav implementace

Prvni vyvojovy zaklad obsahuje:

- Python projekt s CLI vstupem
- nacitani YAML konfigurace s defaultnim nazvem zarizeni podle hostname
- discovery vrstvy pro `.sh` joby
- sekvencni spousteni jobu s predanymi environment promennymi
- zachyceni `stdout`, `stderr`, exit kodu a seznamu vytvorenych souboru
- mount safety kontrolu pro storage s `require_mount`
- generovani finalniho nazvu archivu
- vytvoreni jednoho finalniho `.tar.gz` souboru, ktery obsahuje log a vsechny artefakty z behu
- retention nad finalnimi archivy v cilovem ulozisti
- odeslani alert emailu pri chybe behem backupu
- ukazkove job templaty v `examples/jobs/`

CLI prikaz:

```text
simple-backup run --config config.yaml
```

Pri prime spusteni z repozitare behem vyvoje:

```text
set PYTHONPATH=src
python -m simple_backup.cli run --config config.example.yaml
```

## Jak psat job script

Job je obycejny `.sh` script. Framework ho najde automaticky, pokud:

- ma priponu `.sh`
- neni hidden
- nekonci na `.disabled`
- je executable

Framework jobu preda tyto environment promenne:

- `BACKUP_WORKDIR` cilova pracovni slozka pro artefakty daneho jobu
- `SB_WORK_DIR` kompatibilni alias na stejny workspace pro starsi joby
- `BACKUP_TIMESTAMP` cas behu ve formatu `YYYYMMDDTHHMMSSZ`
- `BACKUP_NAME` nazev jobu odvozeny ze jmena souboru
- `BACKUP_DEVICE_NAME` jmeno stroje z konfigurace
- `BACKUP_TARGET_ROOT` cilovy root pro finalni archiv
- `BACKUP_SCRIPT_PATH` absolutni cesta ke spoustenemu scriptu

Minimalni priklad:

```bash
#!/usr/bin/env bash
set -euo pipefail

: "${SB_WORK_DIR:?SB_WORK_DIR is required}"
: "${BACKUP_NAME:?BACKUP_NAME is required}"
: "${BACKUP_TIMESTAMP:?BACKUP_TIMESTAMP is required}"

JOB_NAME="${BACKUP_NAME}"
OUT_DIR="${SB_WORK_DIR}/${JOB_NAME}"
OUT="${OUT_DIR}/${JOB_NAME}-${BACKUP_TIMESTAMP}.txt"

mkdir -p "${OUT_DIR}"

echo "backup ok" > "$OUT"
```

Doporuceni pro joby:

- pouzivat `set -euo pipefail`
- zapisovat vsechny vystupy jen do `BACKUP_WORKDIR`
- vracet `0` pri uspechu a non-zero pri chybe
- psat prubeh na `stdout` a chyby na `stderr`

Sablony jsou pripraveny v `examples/jobs/`.

## Co vznikne po behu

Po jednom runu vzniknou tyto vystupy:

- jeden finalni archiv v `storage.target_root`
- jeden log soubor v `runtime.log_dir`
- docasne artefakty v `runtime.work_dir`

Finalni archiv obsahuje:

- `log.txt`
- vsechny soubory vytvorene joby pod `artifacts/`

Priklad:

```text
output/
`- myserver-20260313T221500Z.tar.gz

logs/
`- 20260313T221500Z.log
```

## Error notifikace

Pokud backup skonci vyjimkou nebo selze job script, orchestrator muze poslat email podle konfigurace v `notifications.email`.

Email obsahuje:

- nazev selhaneho scriptu `.sh`, pokud je znamy
- nazev stroje
- datum a cas selhani
- text chyby

Priklad predmetu:

```text
[Simple Backup] Selhalo db.sh na stroji myserver 2026-03-13 22:15:00 UTC
```

## Provozni nasazeni

Pro server je rozumny minimalni postup:

1. vytvorit virtualenv
2. nainstalovat projekt pres `pip install .`
3. vytvorit produkcni `config.yaml`
4. vlozit realne joby do `jobs/`
5. spoustet pres cron nebo systemd timer

Jednoduchy cron priklad:

```cron
0 2 * * * /opt/simple-backup/.venv/bin/simple-backup run --config /opt/simple-backup/config.yaml
```

## Vyvoj a testy

Spusteni testu:

```text
set PYTHONPATH=src
python -m unittest discover -s tests
```

Na Linuxu analogicky:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

## Stav v1

Aktualni implementace umi:

- nacist konfiguraci z YAML
- automaticky najit `.sh` joby ve slozce `jobs/`
- spustit joby jeden po druhem
- predat jobum `BACKUP_WORKDIR`, `BACKUP_TIMESTAMP`, `BACKUP_NAME`, `BACKUP_DEVICE_NAME` a `BACKUP_TARGET_ROOT`
- zachytit `stdout`, `stderr`, exit code a vytvorene soubory
- vytvorit jeden finalni archiv s logem a artefakty
- aplikovat retention na finalni archivy
- failnout pri mount checku, pokud je vyzadovan
- poslat alert email se jmenem scriptu, strojem, datem a chybou pri selhani

## Co jeste chybelo a je doplneno

Proti puvodnimu navrhu je ted dodelane i to, ze run log obsahuje retenni mazani starych archivu.

Pro rychly start jsou v `examples/jobs/` i sablony pro:

- PostgreSQL dump
- archivaci souboru

## Stav

Repozitar obsahuje funkcni v1 zaklad orchestratoru pripraveny na pridavani realnych backup jobu.