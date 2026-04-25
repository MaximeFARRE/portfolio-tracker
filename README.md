<!-- Header -->
<div align="center">

# Patrimoine Desktop

**A PyQt6 desktop application for personal and family wealth tracking.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.7%2B-41cd52?style=flat-square&logo=qt&logoColor=white)](https://www.riverbankcomputing.com/software/pyqt/)
[![SQLite](https://img.shields.io/badge/Database-SQLite-003b57?style=flat-square&logo=sqlite&logoColor=white)](https://www.sqlite.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-f0db4f?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-235%20collected-brightgreen?style=flat-square)](tests/)
[![Code style](https://img.shields.io/badge/code%20style-Black-000000?style=flat-square)](https://black.readthedocs.io/)
[![Lint](https://img.shields.io/badge/lint-Ruff-d7ff64?style=flat-square)](https://docs.astral.sh/ruff/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square)](#installation)

</div>

---

## About

Patrimoine Desktop consolidates all your financial accounts — bank, brokerage, savings, credit, real estate, private equity, and business holdings — into a single local desktop application. It tracks portfolio performance, models credit amortization, imports bank transactions, manages import rollbacks, and simulates future wealth trajectories using deterministic, Monte Carlo, and stress-test projection engines.

All data is stored locally in a SQLite database. An optional remote replica via [Turso/libsql](https://turso.tech/) is supported for multi-device sync.

---

## Features

| Domain | Capabilities |
|---|---|
| **Family dashboard** | Consolidated net worth, allocations, cash flow, savings rate, weekly trends |
| **Portfolio tracking** | Live prices via yfinance, weekly history, FX-adjusted positions, performance, Sharpe / VaR / ES / beta analytics |
| **Efficient frontier & backtesting** | Portfolio optimization, benchmark comparison, improved allocation simulation |
| **Credit management** | Amortization schedules, deferred loans, real cost KPIs, remaining capital tracking |
| **Data import** | CSV (expenses, revenues, Bankin), Trade Republic via `pytr`, ticker preview, alias mapping, import history and rollback |
| **Transaction management** | Edit/delete transaction flows with cashflow resynchronization |
| **Projections** | Goal-based projections, native milestones, Monte Carlo simulation, stress scenarios, FIRE targets |
| **Sankey & cash flow** | Visual cash flow breakdown, passive income, family-level flux summaries |
| **PDF export** | Printable wealth summary report |
| **Multi-currency** | FX-adjusted positions, weekly historical FX rates, missing-rate data-quality handling |

---

## Tech stack

| Layer | Technology |
|---|---|
| UI | [PyQt6](https://www.riverbankcomputing.com/software/pyqt/), [Plotly](https://plotly.com/python/) (charts via WebEngine), Matplotlib |
| Data | [pandas](https://pandas.pydata.org/), [NumPy](https://numpy.org/), [SciPy](https://scipy.org/) |
| Market data | [yfinance](https://github.com/ranaroussi/yfinance), OpenFIGI (ISIN resolution), Frankfurter API (FX) |
| Database | SQLite (local) · [libsql/Turso](https://turso.tech/) (optional remote replica) |
| Import | [pytr](https://github.com/pytr-org/pytr) (Trade Republic), CSV pipelines |
| Export | [fpdf2](https://py-pdf.github.io/fpdf2/) |
| Tests & quality | [pytest](https://docs.pytest.org/), [Ruff](https://docs.astral.sh/ruff/), [Black](https://black.readthedocs.io/), pre-commit |

---

## Installation

**Requirements:** Python 3.11+

```bash
# 1. Clone the repository
git clone https://github.com/MaximeFARRE/portfolio-tracker.git
cd portfolio-tracker

# 2. Create a virtual environment
python -m venv .venv

# Windows
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Development setup

```bash
pip install -r requirements-dev.txt
pre-commit install --hook-type pre-commit --hook-type pre-push
```

The local hooks run Ruff and Black automatically before commits and pushes.

### Optional features

**Trade Republic import** (requires a TR account and 2FA setup):
```bash
pip install pytr curl_cffi websockets
```

**Turso remote database** (optional — SQLite works out of the box):
```bash
pip install libsql libsql-client
```
Then copy `.env.example` to `.env` and set your credentials.

---

## Usage

```bash
python main.py
```

The app opens with a family dashboard. Use the left sidebar to navigate between views.

**Data storage:**
- Default: local SQLite database (`~/.patrimoine/patrimoine.db`)
- Logs: `~/.patrimoine/logs/`
- Automatic DB backups on exit: `~/.patrimoine/backups/`

**Remote database (Turso):**  
Set `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` in your `.env` file (see `.env.example`).

---

## Running tests

```bash
pytest
```

235 collected tests covering snapshots, cash flow, passive income, credits, imports, rollbacks, projections, portfolios, FX, backtesting, and UI/service integration.

Code quality checks:

```bash
python -m pre_commit run ruff --all-files
python -m pre_commit run black --all-files
```

---

## Project structure

```text
patrimoine-desktop/
│
├── main.py                     Entry point — logging, DB backup, Qt bootstrap
├── core/
│   └── db_connection.py        Thread-safe DB connection singleton
│
├── db/
│   ├── schema.sql              SQLite schema
│   └── migrations/             Versioned SQL migrations (001 → 005)
│
├── qt_ui/
│   ├── main_window.py          Application shell and navigation
│   ├── theme.py                Color palette and stylesheet constants
│   ├── pages/                  Top-level pages (famille, personnes, import, projection, settings)
│   ├── panels/                 Domain-specific panels (bourse, credit, PE, immobilier…)
│   ├── widgets/                Reusable UI components (DataTable, KpiCard, PlotlyView…)
│   └── components/             Animated containers and skeleton handlers
│
├── services/                   Business logic layer — all KPIs live here
│   ├── bourse_analytics.py     Live positions, FX PnL, weekly performance
│   ├── bourse_advanced_analytics.py  Sharpe, VaR, ES, beta, correlations
│   ├── efficient_frontier.py   Portfolio optimization (scipy)
│   ├── portfolio_backtest_service.py Current portfolio backtesting and improved allocation simulation
│   ├── cashflow.py             Savings rate, passive income, cash flow KPIs
│   ├── credits.py              Amortization schedules and real cost KPIs
│   ├── snapshots*.py           Weekly wealth snapshot computation and rebuild
│   ├── family_snapshots.py     Family-wide consolidated snapshots
│   ├── projections.py          Goal-based projection engine (V1)
│   ├── prevision*.py           Advanced projection engine (Monte Carlo, stress)
│   ├── projection_service.py   Facade routing UI requests to the right engine
│   ├── imports.py              CSV import pipeline
│   ├── import_aliases_service.py Canonical import symbol aliases
│   ├── import_history.py       Import batch tracking and rollback
│   ├── import_lookup_service.py Shared lookup helpers for import UI
│   ├── ticker_preview_service.py Live ticker validation and preview
│   ├── tr_import.py            Trade Republic import pipeline
│   ├── repositories.py         Generic CRUD data access
│   └── db.py                   DB initialization, migrations, sqlite/libsql compat
│
├── utils/                      Shared formatting and validation helpers
├── tests/                      30 test files (pytest)
│
├── docs/
│   ├── ARCHITECTURE.md         Architecture reference (layering, data flows, debt)
│   ├── SOURCE_DE_VERITE.md     Canonical KPI definitions by domain
│   └── CONTEXT.md              Technical context and known deviations
│
├── scripts/
│   └── patrimoine.spec         PyInstaller build spec
│
└── assets/
    └── screenshots/            UI screenshots (see below)
```

---

## Screenshots

> Screenshots coming soon.
>
> The app includes: family net worth dashboard, individual account panels (bank, brokerage, credit, real estate, private equity), projection charts, and a Sankey cash flow view.

---

## Known limitations

- **Two projection engines coexist.** `services/projections.py` (goal-based, V1) and `services/prevision*.py` (Monte Carlo / stress, V2) are both active. `projection_service.py` routes between them. Consolidation is planned but not yet scheduled.
- **FX conversion is not fully unified.** Weekly historical rates, live spot rates, and local helpers still use slightly different sources in some flows.
- **Some analytics flows are still being consolidated.** The service layer is the source of truth, but older panels and compatibility facades are being progressively simplified.
- **No mobile or web interface.** This is a local desktop application only.
- **Trade Republic import requires manual 2FA.** The `pytr` integration prompts for authentication on first use.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch conventions, commit message format, and architecture rules.

The core rule: **all business logic lives in `services/` — the UI layer only handles display and interaction.**

---

## Contributors

| Name | GitHub |
|---|---|
| Maxime Farre | [@MaximeFARRE](https://github.com/MaximeFARRE) |

---

## License

This project is licensed under the [MIT License](LICENSE).
