# Reader fixtures

One directory per source layout. Each is a minimal but REAL project tree — the
readers are tested against trees shaped like the ones they will meet, not against
hand-built dicts that confirm the author's assumption about the shape.

| Directory | Layout | Reader |
|---|---|---|
| `l3io-flat/` | `sprint-status.yaml` with an `epics:` list | `read-l3io-flat.py` |
| `bmad-flat/` | `sprint-status.yaml` with a `development_status:` mapping | `read-bmad-flat.py` |
| `per-epic/` | `_bmad/state/epic-*.yaml`, one file per epic | `read-per-epic.py` |
| `split/` | `sprint-status{,-backlog,-archived}.yaml` | `read-split.py` |
| `artifacts/` | story `.md` files only, no status file | `read-artifacts.py` |

**Every fixture must be referenced by a test.** `test-engine.py` asserts the set of
directories here equals the set of readers — so deleting a fixture fails the suite
instead of silently shrinking the corpus.
