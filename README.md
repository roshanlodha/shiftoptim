# ED Block Schedule Builder

CP-SAT schedule builder for **PGY-4** emergency medicine blocks.

## Web app (primary)

```bash
env/bin/python -m webapp.seed          # first time only
env/bin/python -m webapp.wsgi          # http://127.0.0.1:5000
```

Admin (`jaba` / `thehutt`) runs the solver, reviews drafts, and publishes. Residents view schedules, request time off, and see cumulative history from published runs. All data lives in `data/shiftoptim.db`.

## CLI (legacy)

Edit `config.ini` (block dates, rosters, time off), then:

```bash
env/bin/python -m schedulebuilder.pgy4.schedule 4 5
```

Outputs land in `output/`. Cross-block balance carries in-memory when multiple blocks are solved in one invocation.

## Layout

- `webapp/` — Flask app, SQLite schema, seed data
- `schedulebuilder/pgy4/` — CP-SAT solver, constraints, export
- `config.ini` — CLI input only
- `shiftswap/` — archived shift-trade optimizer
