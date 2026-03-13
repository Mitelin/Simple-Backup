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
```

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

## Error notifikace

Pokud backup skonci vyjimkou nebo selze job script, orchestrator muze poslat email podle konfigurace v `notifications.email`.

Email obsahuje:

- nazev selhaneho scriptu `.sh`, pokud je znamy
- nazev stroje
- datum a cas selhani
- text chyby

## Co jeste chybelo a je doplneno

Proti puvodnimu navrhu je ted dodelane i to, ze run log obsahuje retenni mazani starych archivu.

Pro rychly start jsou v `examples/jobs/` i sablony pro:

- PostgreSQL dump
- archivaci souboru

## Stav

Repozitar obsahuje funkcni v1 zaklad orchestratoru pripraveny na pridavani realnych backup jobu.