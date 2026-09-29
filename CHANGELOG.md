# Changelog

Entries follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), because
`release.yml` extracts the entry for the version being released and **fails the
release when there is none** (AD-30). Add the entry before cutting the tag, not
after.

The `1.5.0` entry below was reconstructed from git history: this file did not
exist when that release was cut, and it is recorded here rather than left blank
so the release has notes at all. Treat it as a summary of the commits in that
range, not as a contemporaneous record.

## [Unreleased]

### Changed

- The mirror publish is idempotent instead of failing on a re-tag, and its
  pre-check reads the name and version from the built wheel rather than from
  `pyproject.toml` — the wheel is what gets published, and the publishing job
  never checks out the repo.
- A published GitHub Release now auto-mirrors, gated by a preflight check that
  reduces the mirror secrets to a boolean. The `secrets` context is not
  available in a job-level `if:`, where it evaluates empty and silently skips.
- `act` picks an ephemeral artifact-server port, so a local run no longer
  collides with whatever already holds the default.

## [1.5.0] - 2026-09-26

### Changed

- Rewritten as `l3io-wp-config` under the `l3io.wp` PEP 420 namespace, shared
  with `l3io-wp-database` and `l3io-wp-backup` (AD-27).
- PyPI publishing is opt-in, and cutting a release no longer depends on it: a
  registry problem must not cost a release.
- `publish-mirror` is gated on the dispatch target, with a mirror-only option,
  so a TestPyPI dry run does not also publish to the internal registry.
- `setup-uv` is pinned to `v10.1.0`; it stopped shipping floating major tags
  after `v7`.

### Added

- Dependency metadata is checked on the shipped artifacts rather than asserted
  in prose — a VCS dependency in published metadata is the defect that left the
  predecessor unresolvable for six years.

### Documentation

- Recorded how downstream repos should depend on this package, the internal
  registry's behaviour (credentials, 404-vs-401, and that the mirror is staging
  rather than a home), and the console script in ADR-0007.
