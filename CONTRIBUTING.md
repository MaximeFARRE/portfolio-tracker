# Contributing to Patrimoine Desktop

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

## Run

```bash
python main.py   # launch the app
pytest           # run all tests
```

## Branch naming

| Type | Pattern |
|---|---|
| Feature | `feat/<description>` |
| Bug fix | `fix/<description>` |
| Chore | `chore/<description>` |
| Docs | `docs/<description>` |

Never commit directly to `main`.

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add PDF export for credit overview
fix: correct soft-delete filter in get_transaction
chore: remove unused imports in main_window
docs: update ARCHITECTURE.md projection section
```

## Architecture

This project enforces a strict layered architecture. Before contributing, read [`AGENTS.md`](AGENTS.md) — it contains the full engineering rules, project-specific constraints, and the definition of done.

The core law: **`qt_ui/` handles display only — all business logic lives in `services/`.**

## Pull request checklist

- [ ] `pytest` passes
- [ ] No SQL or KPI logic added to `qt_ui/`
- [ ] No unused imports introduced
- [ ] `docs/ARCHITECTURE.md` updated if architecture changed
- [ ] Commits follow the convention above
