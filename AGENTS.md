# Patrimoine Desktop — Agent Operating Manual

PyQt6 desktop app for personal and family wealth tracking. Python 3.11+, SQLite, ~130 Python files.

---

## Commands

| Task | Command |
|---|---|
| Run app | `python main.py` |
| Run all tests | `pytest` |
| Run one test | `pytest tests/test_foo.py::test_bar -v` |
| Install runtime deps | `pip install -r requirements.txt` |
| Install dev deps | `pip install -r requirements-dev.txt` |

---

## Repo map

```
main.py              Entry point — logging, DB backup, Qt bootstrap
core/                DB connection singleton (lifecycle only)
services/            ALL business logic, KPIs, analytics (source of truth)
qt_ui/               UI only — pages, panels, widgets, components
  pages/             Top-level views (famille, personnes, import, projection, settings)
  panels/            Domain panels (bourse, credit, PE, immobilier…)
  widgets/           Reusable components (DataTable, KpiCard, PlotlyView…)
db/                  schema.sql + versioned migrations (001–005)
tests/               30 test files, pytest
utils/               Formatting/validation helpers — no business logic
docs/                Architecture and KPI reference docs
scripts/             Build tools (PyInstaller spec)
```

---

## Architecture — enforced strictly

```
qt_ui/ → services/ → repositories.py / db.py
```

- `qt_ui/` handles **display and interaction only**. No SQL. No KPI calculations. No `groupby`, `merge`, `sum`, or `iterrows` to derive business data.
- All business logic lives in `services/`. Every KPI has exactly one canonical function. Find it before creating another.
- `services/repositories.py` — generic CRUD. `*_repository.py` files — domain-specific data access.
- `services/db.py` — DB initialization, migrations, sqlite/libsql compatibility layer.

---

## Project-specific constraints

| Rule | Detail |
|---|---|
| DB connection | Use `self._conn`. Never create a new connection inside a panel or service method. |
| Long operations | Run in a `QThread`. Never block the Qt main thread. |
| Dates | `YYYY-MM-DD`. Monthly buckets stored as `YYYY-MM-01`. |
| Amounts | `transactions.amount` is always positive. Direction comes from `type`. |
| Private functions | Never call `_prefixed` functions from outside their own module. |
| Projection engines | Two coexist: `projections.py` (V1, goal-based) and `prevision*.py` (V2, Monte Carlo/stress). Always route via `projection_service.py`. Never call either engine directly from the UI. |
| Snapshots | Past snapshots are never recalculated on the fly. Use the snapshot read layer (`snapshots_read.py`). |
| Cashflow KPIs | Always via `cashflow.py`. Never recompute inline. |
| Bourse positions | Always via `bourse_analytics.py`. Never recompute in a panel. |

---

## Key service files

| File | Owns |
|---|---|
| `cashflow.py` | Savings rate, passive income, cash flow KPIs |
| `bourse_analytics.py` | Live positions, FX PnL, weekly performance |
| `bourse_advanced_analytics.py` | Sharpe, VaR, ES, beta, correlations |
| `efficient_frontier.py` | Portfolio optimization |
| `credits.py` | Amortization schedules, real cost KPIs |
| `snapshots.py` (facade) | Weekly wealth snapshot entry point |
| `repositories.py` | Generic CRUD |
| `projection_service.py` | Projection routing facade |
| `liquidites.py` | Cash and savings account summary |

---

## Before creating anything

1. Search `services/` for a function that already does what you need.
2. If close, extend the existing service — don't create a parallel one.
3. Create a new file only if no existing module is remotely relevant.
4. Never duplicate logic across services.

---

## Code style

- One function = one responsibility. Target < 50 lines per function.
- Explicit names: `live_positions` not `x`. Intermediate variables over complex one-liners.
- Every public function gets a one-line docstring.
- Early returns over nested conditionals. Max 3 levels of nesting.
- Type-hint all function signatures.
- Never `except: pass`. Always log errors. Always handle missing data explicitly.

---

## Never do

- Commit directly to `main`.
- Add SQL or KPI logic to `qt_ui/`.
- Duplicate a calculation already present in a service.
- Rewrite a whole file when a small change suffices.
- Mix unrelated changes in one commit or one task.
- Silently swallow exceptions.
- Call `_private` functions from outside their module.
- Add unused imports.
- Claim something was tested when it was not run.

---

## Git conventions

- Branch prefixes: `feat/`, `fix/`, `chore/`, `docs/`, `test/`
- Commit format: `type: short description` (Conventional Commits)
- Commit after each logical step. Small, focused commits.
- Never batch unrelated changes.

---

## Definition of done

Before marking a task complete:

- [ ] `pytest` passes with no new failures
- [ ] No business logic added to `qt_ui/`
- [ ] No logic duplicated from an existing service
- [ ] No unused imports introduced
- [ ] No `_private` function called from outside its module
- [ ] Behavior is unchanged where it was not asked to change
- [ ] Any moved or renamed file has its cross-references updated
