# Changelog

Entries follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), because
`release.yml` extracts the entry for the version being released and **fails the
release when there is none** (AD-30). Add the entry before cutting the tag, not
after — nothing writes this file for you. The tooling only ever reads it: the
pre-tag gate in `release.yml`, the release notes in `publish.yml`, and `make
release status`.

**On the version restart.** A `1.5.0` was tagged on 2026-09-26, mirrored to the
internal registry, and then fully withdrawn — tag deleted, registry entry
removed, GitHub release deleted — when this family restarted its versioning from
scratch. Nothing ever resolved from it. The `1.0.0` entry below therefore covers
everything that work contained, reconstructed from git history rather than
written contemporaneously: treat it as a summary of the commit range, not as a
record kept at the time.

## [Unreleased]

## [1.0.0] - 2026-09-29

First release of the rewritten package.

### Changed

- Rewritten as `l3io-wp-config` under the `l3io.wp` PEP 420 namespace, shared
  with `l3io-wp-database` and `l3io-wp-backup` (AD-27).
- PyPI publishing is opt-in, and cutting a release no longer depends on it: a
  registry problem must not cost a release.
- `publish-mirror` is gated on the dispatch target, with a mirror-only option,
  so a TestPyPI dry run does not also publish to the internal registry.
- The mirror publish is idempotent instead of failing on a re-tag, and its
  pre-check reads the name and version from the built wheel rather than from
  `pyproject.toml` — the wheel is what gets published, and the publishing job
  never checks out the repo.
- A published GitHub Release now auto-mirrors, gated by a preflight check that
  reduces the mirror secrets to a boolean. The `secrets` context is not
  available in a job-level `if:`, where it evaluates empty and silently skips.
- `setup-uv` is pinned to `v10.1.0`; it stopped shipping floating major tags
  after `v7`, so `@v10` resolves nowhere.
- `git-action-changelog-parser` is pinned to `v2`. It was `@v3`, which does not
  exist — that action publishes floating majors `v1` and `v2` only, so every
  release would have failed at this file's own gate.
- `act` picks an ephemeral artifact-server port, so a local replay no longer
  collides with whatever already holds the default.

### Added

- Dependency metadata is checked on the shipped artifacts rather than asserted
  in prose — a VCS dependency in published metadata is the defect that left the
  predecessor unresolvable for six years.

### Documentation

- Recorded how downstream repos should depend on this package, the internal
  registry's behaviour (credentials, 404-vs-401, and that the mirror is staging
  rather than a home), and the console script in ADR-0007.
