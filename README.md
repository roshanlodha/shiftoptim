# ED Block Schedule Builder

CP-SAT schedule builder for **PGY-4** emergency medicine blocks. PGY-1/2/3 builders will share the same ACGME-style constraints but use different shift catalogs and count rules.

## PGY-4 usage

Edit `config.ini` (block dates, rosters, time off), then:

```bash
env/bin/python -m schedulebuilder.pgy4.schedule          # defaults to blocks 4 5
env/bin/python -m schedulebuilder.pgy4.schedule 4 5 --min 8 --time 60
```

Outputs land in `output/` (`block{N}_grid.csv`, `block{N}_summary.csv`). Cross-block wellness balance is tracked in `data/history.json`.

## Layout

- `schedulebuilder/pgy4/` — PGY-4 solver, constraints, export
- `config.ini` — PGY-4 admin input (dates, rosters, time off)
- `data/history.json` — cross-block ledger
- `shiftswap/` — archived shift-trade optimizer (see `shiftswap/README.md`)
