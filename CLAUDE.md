# CLAUDE.md

**Read `AGENTS.md` fully before starting any task in this repository.**

Engineering rules, project-specific constraints, architecture law, and the definition of done are all in `AGENTS.md`. Do not skip it.

---

## Source of truth files

| File | Purpose |
|---|---|
| `AGENTS.md` | Engineering rules, commands, architecture, done checklist |
| `docs/ARCHITECTURE.md` | Full layering reference, data flows, known debt |
| `docs/SOURCE_DE_VERITE.md` | Canonical KPI function per domain |

If multiple implementations of the same calculation exist, use the one declared in `docs/SOURCE_DE_VERITE.md`.

---

## Claude-specific behavior

- **Check the branch first.** Run `git branch` before editing anything. Never commit to `main`.
- **Read before editing.** Open and read any file before modifying it.
- **Minimal changes.** Do exactly what was asked. Do not clean up unrelated code in the same task.
- **State assumptions.** If a task is ambiguous, state your interpretation before writing code.
- **Commit at each logical step.** Use `type: description` format. Do not accumulate all changes into one commit at the end.
- **Before finishing**: run `pytest`, review the diff, and report what changed and why.
- **Do not invent.** If a fact about the codebase is uncertain, read the relevant file rather than guessing.
