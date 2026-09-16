<!-- bmad:context -->
<!-- Verified 2026-09-16 against 8f25bb8 plus the uncommitted rewrite. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## py-wpconfigr → l3io-wp-config

Reads and writes `define()` constants and file-scope variable assignments in a
WordPress `wp-config.php`. A fork of `cariad/py-wpconfigr` (MIT), rewritten as
`l3io-wp-config`, importing as `l3io.wp.config`, released **first** of three
packages — nothing else ships until this resolves from PyPI. Zero runtime
dependencies; hatchling and uv; `src/` layout.

Governing documents live in the `py-wordpress-backup` repo and are authoritative.
Read them rather than re-deriving their decisions; if one looks wrong, say so and
stop.

## Policy

- **Never create `__init__.py` at `l3io/` or `l3io/wp/`.** Only `src/l3io/wp/config/`
  and below. An `__init__.py` above that level makes this a regular package, shadows
  the PEP 420 namespace, and makes `l3io-wp-database` and `l3io-wp-backup`
  unimportable — while this package's own tests still pass, because the failure
  appears only once two are installed together. **mypy will suggest adding one**;
  do not. `tests/test_architecture.py` fails if one appears. (AD-27)
- **Zero runtime dependencies, permanently** — including `structlog`. Emit through
  stdlib `logging.getLogger(__name__)`; the application's `ProcessorFormatter` picks
  the records up. `[project].dependencies` must stay empty. (AD-2, AD-10)
- Never publish to PyPI. Finish with a verified artifact and hand back; a human
  releases.
- Version must be **1.5.0 or higher**. PyPI burns filenames permanently, so the
  fork's 1.4 can never be re-uploaded. `publish.yml`'s version-gate enforces this
  and also fails when the tag and `pyproject.toml` disagree.
- Do not widen the parser beyond `define()` and simple file-scope variable
  assignments, and do not add a runtime dependency for any reason.
- Keep `Copyright (c) 2018 Cariad Eccleston` in `LICENSE` — MIT requires it — and
  credit the fork origin in `README.md`, naming upstream's own successor
  `wpconfigger`. `README.md` still carries upstream's badge and install
  instructions; it has not been rewritten yet.

## Where things are

- Authoritative decisions, in `../py-wordpress-backup/`:
  `_bmad-output/implementation-artifacts/handoffs/` (start with `00-SHARED-CONTEXT.md`,
  then `01-l3io-wp-config.md`), `docs/adr/` (13 records), and
  `_bmad-output/planning-artifacts/architecture/architecture-py-wordpress-backup-2026-09-15/ARCHITECTURE-SPINE.md`.
- `domain/` values and errors · `core/` pure parsing, rendering and verification ·
  `ports/` the Protocol · `adapters/` file I/O · `cli/` the command line.
- `core/` and `domain/` must import no I/O module and nothing outward of them;
  `tests/test_architecture.py` checks both by AST. (AD-1)

## Running and verifying

- `uv sync --locked` then `uv run pytest`. Expect **82 passing at ~90% coverage**.
- **Do not run `uv self update`.** `[tool.uv] required-version` pins `==0.11.6` to
  match CI; a different uv writes a lock CI rejects. Change both together or neither.
- `make check` runs lint, types, contracts and tests — everything CI's static,
  contracts and test jobs run. `make ci` replays the whole pipeline locally under
  nektos/act; `make ci-job JOB=<id>` replays one.
- **Every CI job runs locally under act; nothing is gated off.** `ci.yml` builds
  its wheel inside the verify-install job rather than passing an artifact between
  jobs — the round trip is plumbing, not an invariant, and act's server does not
  speak the `upload-artifact` v6/v7 protocol (v5 does, but it is `node20` and
  leaves the runner images 2026-09-23). `publish.yml` keeps the artifact steps,
  because build-once-publish-exactly-that is a real requirement there, and act
  never runs it.
- Verify against the **built wheel installed into a clean environment**, never the
  working tree. Installing the working tree would have passed throughout the entire
  six-year outage; that is the blind spot this closes.

## Conventions that differ from defaults

- `get()` and `get_variable()` return `MISSING`, never `None`, for an absent key.
  A key set to `false`, `0` or `''` is present and falsy, so test `is MISSING`
  rather than truthiness.
- `define()` constants and `$variables` are separate namespaces: `get`/`set` reach
  constants, `get_variable`/`set_variable` reach variables. `$table_prefix` is a
  variable, and `l3io-wp-database` needs it to locate site metadata.
- Every `WpConfigFile.set()` re-reads and verifies before committing, so a write
  can raise `ReadBackError`. On failure the original file is untouched. (ADR-0010)
- Only package-owned exceptions cross the public boundary — never `OSError`,
  `TypeError` or `ValueError`. Catch at the boundary and `raise ... from`. (AD-14)

## CI conventions

- Prefer `LiquidLogicLabs/*` actions over third-party ones or hand-rolled `run:`
  steps.
- Verify a pin with `git ls-remote --tags` and read **all** the tags, not just the
  floating majors. `astral-sh/setup-uv` stopped publishing floating majors after
  `v7` but has exact tags through `v10.1.0`, so `@v10` resolves nowhere while
  `@v10.1.0` is current — and a `grep -E '^v[0-9]+$'` hides that entirely by
  matching only floating majors. Not every publisher ships them; `actions/*` do.
- Never set `UV_FROZEN` alongside `uv sync --locked` — uv rejects the combination.
- Every job sets `UV_PROJECT_ENVIRONMENT` to a `/tmp` path outside the workspace.
  `~/.actrc` uses `--bind`, so without it a local replay races four matrix jobs
  over one `.venv` and leaves it root-owned, breaking every later `uv` command.
  `runner.temp` does not work here — the `runner` context is step-level only.
- Prefer restructuring over gating. The one `vars.LOCAL_ACT` use left is cache
  tuning, not a skipped step. If a difference is genuinely unavoidable, express it
  through `vars.LOCAL_ACT` and never `env.ACT`: `env.ACT` does not work in a
  job-level `if:`, and Gitea runners also set `ACT=true`.
- `publish.yml` is a separate file and act must never run it; `.actrc` pins act to
  `ci.yml`. act has no OIDC and ignores `job.permissions`, so an `if:` guard would
  not protect it.

## Known pitfalls

- Read-back compares the rendered **value** text, not the whole statement.
  WordPress writes `define( 'X', 'y' );` with inner spaces and a write preserves
  that formatting, so comparing whole statements against a canonical rendering
  rejects correct writes to almost every real `wp-config.php`.
- Only single-quoted values parse as strings. `define('X', "y")` returns the raw
  text `"y"`, quotes included, and a PHP expression returns its source text.
  Both are accepted limits, not bugs to fix here. (ADR-0010)
- `tests/wp-config-sample.expected.php` once encoded the old greedy-match bug,
  which dropped the space in `define( 'WP_DEBUG', true );`. If a fixture and the
  code disagree, check which one recorded a defect before trusting the fixture.

<!-- /bmad:context -->
