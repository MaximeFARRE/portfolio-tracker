# Contributing to Patrimoine Desktop

Thank you for your interest in contributing. This document covers the conventions and rules to follow.

## Prerequisites

- Python 3.11+
- A virtual environment (recommended)

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## Running the app

```bash
python main.py
```

## Running the tests

```bash
pytest
```

All tests must pass before opening a pull request.

## Branch naming

| Type | Pattern | Example |
|---|---|---|
| Feature | `feat/<short-description>` | `feat/export-pdf` |
| Bug fix | `fix/<short-description>` | `fix/snapshot-rebuild` |
| Chore / cleanup | `chore/<short-description>` | `chore/clean-imports` |
| Documentation | `docs/<short-description>` | `docs/update-architecture` |

**Never commit directly to `main`.**

## Commit message convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short description>

# Examples:
feat: add PDF export for credit overview
fix: correct soft-delete filter in get_transaction
chore: remove unused imports in main_window
docs: update ARCHITECTURE.md projection section
```

Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`

## Architecture rules

This project follows a strict layered architecture:

```
qt_ui/ (pages, panels, widgets)
  → services/          business logic, KPIs, calculations
    → repositories/    data access (SQL)
      → db/            schema and migrations
```

**Rules:**
- `qt_ui/` must only handle display and user interaction — no SQL, no business calculations.
- All business logic (KPIs, aggregations, projections) lives in `services/`.
- Never duplicate a calculation already present in a service.
- Never call a private function (`_prefixed`) from outside its module.
- Before creating a new function, check if one already exists in `services/`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full architecture reference.

## Adding a new feature

1. Identify the relevant service in `services/`.
2. Implement business logic in the service, not in the UI.
3. Wire the UI panel to call the service.
4. Add or update tests in `tests/`.
5. Update `docs/SOURCE_DE_VERITE.md` if you add a new canonical KPI.

## Pull request checklist

- [ ] Tests pass (`pytest`)
- [ ] No SQL or business logic added directly in `qt_ui/`
- [ ] No unused imports introduced
- [ ] `docs/ARCHITECTURE.md` updated if architecture changed
- [ ] Commit messages follow the convention above
