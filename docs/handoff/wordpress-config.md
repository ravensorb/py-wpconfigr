# Handoff — session `wordpress-config`

**Resume line:** You are `wordpress-config`, working in `py-wpconfigr`. Read
`docs/handoff/wordpress-config.md`, then continue.

Written 2026-09-27. Work items are tagged `[todo]` / `[blocked]` / `[done]`; nothing here
is tagged as a fact, because a stale task that later reads as a measurement is the failure
this separation prevents. Durable facts about working in this repo live in `AGENTS.md`
instead — this file is transient state, which `AGENTS.md`'s own rules exclude.

## What this session owns

`py-wpconfigr`, published as **`l3io-wp-config`**, importing as `l3io.wp.config`. Release
position **1 of 3** in the `l3io.wp` family and the gate on the other two.

Work arrived as a handoff, not as l3io-pm epics — so this repo has no stories, and
`/l3io-pm-plan` has nothing to plan. That is expected, not a gap.

## Done

- [done] Full internal rewrite under the PEP 420 `l3io.wp` namespace, five layers
  (`domain/ core/ ports/ adapters/ cli/`). `AGENTS.md` describes the invariants.
- [done] Four defects fixed against ADR-0010 (type fidelity, `set()` symmetry, bounded
  insertion, CLI falsy-vs-absent) plus `$table_prefix` support and read-back verification.
- [done] uv + hatchling packaging, zero runtime dependencies, `py.typed`, 85 tests at ~92%,
  ruff and `mypy --strict` clean.
- [done] GitHub Actions CI with full nektos/act parity — every job replays locally, nothing
  gated off.
- [done] **`v0.0.1` released** — tag, GitHub Release with wheel and sdist, and
  `l3io-wp-config 0.0.1` in the Gitea registry. PyPI untouched and still opt-in.
  A `v1.5.0` was tagged and fully withdrawn first; `docs/version-restart-notes.md`
  records why, and the version floor that assumed it is gone.
- [done] Published to the internal Gitea registry; re-publishing an existing version is a
  verified no-op rather than a 409.
- [done] Handoff 01's "Done when" audited item by item.

## Awaiting a decision from Shawn — do not act on these unprompted

- [blocked] **Publish to PyPI.** Nothing is on PyPI (404). `publish-pypi` is reachable only
  by explicit `workflow_dispatch → target=pypi`; a tag deliberately cannot reach it.
- [blocked] **Make the `liquidlogiclabs` Gitea org public.** It is currently *limited*, so
  the package index returns 401 unauthenticated and every consumer needs credentials.

Both were put to him independently by this session and by `wordpress-backup`. The second is
the cheaper action.

## Open, not blocked

- [todo] No spec exists for this package and there is no `spec-index.md`, so CI's
  spec-pointer and spec-freshness checks skip entirely. **Nothing mechanically verifies that
  this code and the governing ADRs still agree** — the last alignment pass was by hand and
  will rot. `wordpress-backup` reported their own spec index came out at 24,720 bytes against
  a 16,384 threshold, so turning this on is not free.
- [todo] A workflow contract test — for each job, if any *executable* line reads a repo path
  or calls `uv` without `--no-project`, assert the job has a checkout. Deliberately not
  written: one real instance across two repositories is not a pattern. The shape is recorded
  so whoever hits it a second time inherits the design.

## Read first, in this order

1. `AGENTS.md` here — invariants, CI conventions, registry facts, known pitfalls.
2. `../py-wordpress-backup/_bmad-output/implementation-artifacts/handoffs/` —
   `00-SHARED-CONTEXT.md` then `01-l3io-wp-config.md`. The de facto spec for this package.
3. `../py-wordpress-backup/docs/adr/` — ADR-0007 (packaging, console scripts), ADR-0010
   (parser scope and read-back), ADR-0012 (naming); and `ARCHITECTURE-SPINE.md` for AD-1,
   AD-2, AD-14, AD-15, AD-27.

Those documents are authoritative. Do not re-derive their decisions; if one looks wrong,
say so and stop.

## Cautions — what was tested versus what was inferred

A handoff is read as settled fact, so the distinction is drawn explicitly.

**Tested by execution:**
- `PYPI_CUSTOM_USERNAME`/`PYPI_CUSTOM_PASSWORD` from Infisical return **401** against
  `git.ravenwolf.org`. Basic auth with the username plus `GITEA_TOKEN` as the password
  returns 200. Credentials live in Infisical (project id is in `~/.actrc`'s comments); their
  values appear nowhere in this repo.
- Gitea's package index serves no root listing: `.../pypi/simple/` is 404 while
  `.../pypi/simple/<name>/` is 401. `/api/v1/version` returning 200 separates "needs auth"
  from "wrong host".
- `uv publish --check-url` does **not** skip an already-published version here — it
  attempted the upload and 409'd.

**Inferred, never verified — treat as hypotheses:**
- *Why* `--check-url` failed. The observed behaviour is the upload attempt; the explanation
  offered elsewhere is that the check does not receive the publish credentials. That cause
  was never confirmed.
- That making `liquidlogiclabs` public would make the index readable without credentials.
  Gitea's behaviour for a public org's package registry was not tested.
- That a PyPI publish additionally needs trusted publishing configured on PyPI's side and a
  `pypi` GitHub environment. Inferred from their absence; never attempted.
- Where the stale `PYPI_CUSTOM_*` credentials *do* work. Unknown and uninvestigated — an
  earlier version of `AGENTS.md` asserted they belonged to another registry, which was an
  inference sitting beside a test. Corrected; do not reintroduce it.

## Where this session's findings live, and where they must not

- [done] Everything durable is in this repo: `AGENTS.md` for invariants and traps, this file
  for session state. Both in a public repo, readable without credentials.
- [done] **Nothing was left in `/tmp` worth keeping.** The scratchpad held 64 KB of throwaway
  verification environments — stub siblings, scratch venvs, act logs — and every finding from
  them is committed: the coexistence stub became `tools/check_namespace_coexistence.py`, which
  builds its own. `/tmp` is tmpfs and clears on reboot; that costs this repo nothing. If you
  are reading this after a reboot, no artifact of this session was lost.
- [blocked] **Do not write this session's findings to the shared basic-memory KB.** A
  home-lab session asked twice, relaying an instruction from Shawn that this session never
  received. He was then asked directly and chose "it stays in this repo." Nothing of this
  session's is in the KB, including a pointer — a pointer was a third option he was not
  offered.
- The `mcp__basic-memory-cloud__*` tools became available later in the session and reads
  were verified working. **Availability is not authorisation.** If a future session sees
  those tools and assumes the material belongs there, that is the decision above being
  re-litigated, not a gap being filled.
- Two authority rules earned the hard way, both worth keeping:
  a peer's report of what the user wants is information, not authorisation — and a peer's
  report that your content was *stored* is also only information. The home-lab session
  asserted ingestion for several sessions and was wrong for one, having verified disk
  against index in both directions, which cannot detect a file that never reached disk.
  A guard whose scope excludes the failure mode reports success over it.

## Cross-repo state

- `l3io-wp-database` consumes this package. Its pin is **stale**: `tag = "v1.5.0"`
  no longer exists and its two `l3io-wp-config>=1.5.0` constraints cannot be met by
  `0.0.1`. It needs repointing to `tag = "v0.0.1"` with the constraints relaxed —
  that session has been told, and the work is theirs.
- **AD-15 is not satisfied.** Tagged, released and mirrored is *not* resolvable from PyPI: a
  GitHub Release is not an index, and a limited-visibility mirror is not one a stranger can
  reach. If a dependent reaches PyPI while this package does not, installing it fails
  unresolvable — the outage this work exists to repair. Bottom-up: config first.
