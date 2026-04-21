# Changelog

All notable changes to this project are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- `docs/` folder: ARCHITECTURE.md, SOURCE_DE_VERITE.md, CONTEXT.md moved from root
- `scripts/` folder: PyInstaller spec moved from root
- `assets/screenshots/` placeholder for UI screenshots
- `LICENSE` (MIT)
- `CONTRIBUTING.md` with branch, commit, and architecture conventions
- `CHANGELOG.md` (this file)
- `.env.example` documenting Turso/libsql environment variables
- Import aliases service (`services/import_aliases_service.py`)
- Ticker preview service (`services/ticker_preview_service.py`)
- Efficient frontier optimization (`services/efficient_frontier.py`)
- Family snapshots service (`services/family_snapshots.py`)
- Revenues repository (`services/revenus_repository.py`)
- Generic account panel (`qt_ui/panels/compte_generic_panel.py`)
- Asset edit dialog (`qt_ui/panels/edit_asset_dialog.py`)
- Asset panel mapping service (`services/asset_panel_mapping.py`)

### Changed
- `readme.md` renamed to `README.md`
- Duplicate PyInstaller spec (`Patrimoine Desktop.spec`) removed
- Legacy Streamlit code (`legacy/`, `pages/`) removed
- Root debug scripts (`_check_db.py`, `_test_analytics.py`) removed
- `.devcontainer/` untracked (already covered by .gitignore)
- Unused imports cleaned in `qt_ui/main_window.py` and `qt_ui/pages/famille_page.py`
- `docs/ARCHITECTURE.md`: dual projection engine documented, Streamlit references removed

### Security
- `patrimoine_turso.db` purged from git history (contained user financial data)

---

## [0.1.0] — 2024

### Added
- Initial PyQt6 desktop application
- SQLite local database with versioned migrations
- Account management: BANQUE, BOURSE, LIVRET, CREDIT, IMMOBILIER, PE, ENTREPRISE
- Portfolio tracking with live prices via yfinance
- CSV import pipeline (expenses, revenues, Bankin)
- Trade Republic import via pytr
- Weekly snapshot system for portfolio valuation
- Cashflow and savings rate calculations
- Credit amortization and KPIs
- Goals & projection page (deterministic engine)
- Advanced projection: Monte Carlo, stress tests
- Family dashboard with consolidated view
- PDF export
- FX handling and multi-currency positions
