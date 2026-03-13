# Simple Backup

Simple Backup je jednoduchy backup framework pro Linux server. Aplikace bude fungovat jako orchestrator, ktery automaticky najde uzivatelske shell joby, spusti je, prevezme jejich vystupy a ulozi backupy do zvoleneho uloziste.

## Cile projektu

- jednoducha instalace a provoz na serveru
- minimalni globalni konfigurace
- automaticke hledani job skriptu ve slozce `jobs/`
- modularni pristup bez nutnosti registrovat joby v konfiguraci
- zaklad pro retention, logovani a pozdejsi rozsireni

## Navrhovany princip

Framework bude resit:

- nacteni konfigurace
- discovery spustitelnych `.sh` jobu
- spousteni jobu s predanym runtime kontextem
- prevzeti vystupnich souboru z pracovni slozky
- ulozeni backupu do storage
- jednoduchy logging a retention politiku

Job samotny resi konkretni backup logiku, napr. SQL dump nebo export souboru.

## Ocekavane pouziti

1. upravit globalni `config.yaml`
2. vlozit vlastni shell skripty do `jobs/`
3. nastavit jim executable prava
4. spustit orchestrator

## Predbezny config

```yaml
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

## Plan vyvoje

- pripravit zakladni Python aplikaci orchestratoru
- navrhnout nacteni konfigurace a validaci
- doplnit discovery a spousteni jobu
- doplnit storage layout, logovani a retention
- pridat ukazkove job skripty a dokumentaci nasazeni

## Stav

Repozitar je pripraven pro inicialni vyvoj.