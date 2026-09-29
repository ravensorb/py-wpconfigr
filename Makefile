# l3io-wp-config — local developer entry points.
#
# CI is replayed locally with nektos/act, configured by .actrc plus
# .act.{vars,env,secrets}. The same workflow files run here and on GitHub.
#
# First-time setup:
#   make act-init   copies .act.{vars,env,secrets}.example -> .act.{vars,env,secrets}
#
# Unlike the sibling repositories, `make ci` does NOT run under `infisical run`:
# ci.yml declares no secrets, because this package has no database, no registry
# step and no publish path in CI. publish.yml does need credentials, and act
# never runs it.
#
# Useful targets:
#   make lint         ruff check + format --check
#   make types        mypy --strict
#   make test         pytest
#   make contracts    the architecture gates (AD-27, AD-1, AD-2)
#   make check        lint + types + contracts + test, the whole local gate
#   make ci           replay the whole CI pipeline locally via act
#   make ci-job JOB=  replay one job, e.g. make ci-job JOB=contracts
#   make ci-dryrun    parse and plan the workflow without running it
#   make build        uv build --no-sources

ACT_FILES := .act.vars .act.env .act.secrets
UV := uv

# ~/.actrc declares shared publish and registry credentials as bare `-s NAME`
# for the sibling repositories. act prompts for any it cannot resolve and then
# fails outside a TTY, which blocks local replay entirely. ci.yml here uses none
# of them -- this package has no database, no registry step and no publish path
# in CI -- so they are resolved to an obvious placeholder.
#
# The placeholder must be NON-EMPTY: act treats an empty environment value as
# unset and prompts anyway, then fails outside a TTY. `--secret-file` does not
# satisfy a bare `-s NAME` declaration at all; only the environment does.
#
# GITHUB_TOKEN is excluded deliberately: act does not prompt for it when absent,
# and a PLACEHOLDER value is worse than none -- act hands it to git when fetching
# actions, and GitHub rejects it, so action resolution fails. Absent means an
# anonymous clone, which is what these public actions need.
#
# The list is read from ~/.actrc rather than written out here, so it cannot
# drift from what act actually declares.
#
# publish.yml is the one place these matter, and act never runs it (see .actrc).
# Supply them through `infisical run` when that changes.
ACT_BARE_SECRETS := $(shell grep -hE '^-s [A-Za-z_][A-Za-z0-9_]*$$' $(HOME)/.actrc 2>/dev/null | awk '{print $$2}' | grep -v '^GITHUB_TOKEN$$')
ACT := env $(foreach s,$(ACT_BARE_SECRETS),$(s)=unused-by-this-repo) act

.PHONY: help act-init lint format types test contracts namespace-check check ci ci-job ci-dryrun ci-list build verify-wheel clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

# Bootstrap any .act.* file from its .example counterpart on first use.
$(ACT_FILES): %: %.example
	@if [ ! -f $@ ]; then cp $< $@; echo "Created $@ from $<."; fi

act-init: $(ACT_FILES) ## Bootstrap .act.{vars,env,secrets} from .example versions

# Scoped to src and tests, exactly as ci.yml's static job is. If these two ever
# disagree, `make check` stops predicting CI, which is the only thing it is for.
lint: ## ruff lint + format check
	$(UV) run ruff check src tests tools
	$(UV) run ruff format --check src tests tools

format: ## Apply ruff formatting
	$(UV) run ruff format src tests tools
	$(UV) run ruff check --fix src tests tools

types: ## mypy --strict
	$(UV) run mypy

contracts: ## Architecture contract gates (AD-27, AD-1, AD-2)
	$(UV) run pytest tests/test_architecture.py -q

namespace-check: ## AD-27: prove the namespace survives a sibling distribution
	$(UV) run python tools/check_namespace_coexistence.py

test: ## Run the test suite
	$(UV) run pytest -q

check: lint types contracts namespace-check test ## Everything CI's static/contracts/test jobs run

build: ## Build wheel + sdist
	$(UV) build --no-sources

verify-wheel: build ## Install the built wheel into a clean environment and import it
	@set -eu; \
	wheel=$$(ls -t dist/*.whl | head -1); \
	$(UV) run --isolated --no-project --with "$$wheel" \
	  python -c "from l3io.wp import config; print('import ok', sorted(config.__all__))"

# ---- local CI replay -------------------------------------------------------

ci: act-init ## Replay the full CI pipeline locally
	$(ACT) push

ci-job: act-init ## Replay one job: make ci-job JOB=contracts
	@test -n "$(JOB)" || { echo "usage: make ci-job JOB=<job-id>"; exit 2; }
	$(ACT) push -j $(JOB)

ci-dryrun: act-init ## Parse and plan the workflow without executing it
	$(ACT) push --dryrun

ci-list: act-init ## List the jobs act can see
	$(ACT) push --list

clean: ## Remove build and cache artifacts
	rm -rf dist build .artifacts .uv-cache .pytest_cache .mypy_cache .ruff_cache
	find . -name '__pycache__' -prune -exec rm -rf {} +

# ---------------------------------------------------------------------------
# Releasing
#
# These targets do NOT compute a version, build, or publish. They dispatch
# release.yml and stop. The version is derived from the git tag by hatch-vcs
# (AD-30), so anything that worked out a version locally would be a second
# implementation of the one thing that must have exactly one.
#
# `make release patch` and `make release BUMP=patch` are the same command. The
# bare words are no-op targets that exist only so make does not fail on the
# second goal.
# ---------------------------------------------------------------------------

GH ?= gh
RELEASE_WORKFLOW ?= release.yml
RELEASE_BRANCH ?= main
BUMP ?=

_BUMP_WORDS := patch minor major dev
_BUMP_GOAL := $(firstword $(filter $(_BUMP_WORDS),$(MAKECMDGOALS)))
_BUMP := $(if $(BUMP),$(BUMP),$(_BUMP_GOAL))

.PHONY: release release-patch release-minor release-major release-dev $(_BUMP_WORDS)

release: ## Cut a release: make release patch|minor|major|dev
	@set -eu; \
	bump="$(_BUMP)"; \
	if [ -z "$$bump" ]; then \
	  echo "usage: make release patch|minor|major|dev   (or make release BUMP=patch)"; \
	  exit 2; \
	fi; \
	case "$$bump" in patch|minor|major|dev) ;; *) echo "unknown bump '$$bump'"; exit 2 ;; esac; \
	command -v $(GH) >/dev/null || { echo "gh is not installed"; exit 1; }; \
	$(GH) auth status >/dev/null 2>&1 || { echo "gh is not authenticated: run 'gh auth login'"; exit 1; }; \
	branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" != "$(RELEASE_BRANCH)" ]; then \
	  echo "on '$$branch', not '$(RELEASE_BRANCH)' -- release.yml tags whatever it checks out"; exit 1; \
	fi; \
	if [ -n "$$(git status --porcelain --untracked-files=no)" ]; then \
	  echo "tracked files are modified. That work is NOT in the release, and a dirty"; \
	  echo "tree also makes a local build report a different version than the tag."; \
	  git status --short --untracked-files=no; exit 1; \
	fi; \
	git fetch --quiet origin $(RELEASE_BRANCH); \
	if [ "$$(git rev-parse HEAD)" != "$$(git rev-parse origin/$(RELEASE_BRANCH))" ]; then \
	  echo "HEAD and origin/$(RELEASE_BRANCH) differ -- the workflow releases the PUSHED commit,"; \
	  echo "so push or pull first. Local: $$(git rev-parse --short HEAD)  origin: $$(git rev-parse --short origin/$(RELEASE_BRANCH))"; \
	  exit 1; \
	fi; \
	latest=$$(git tag -l 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | head -1); \
	echo "  repo         $$($(GH) repo view --json nameWithOwner -q .nameWithOwner)"; \
	echo "  commit       $$(git rev-parse --short HEAD)"; \
	echo "  latest tag   $${latest:-<none: the first release will be v1.0.0>}"; \
	echo "  changelog    $$(grep -m1 '^## \[' CHANGELOG.md 2>/dev/null || echo '<no Keep-a-Changelog entry found>')"; \
	echo "  bump         $$bump"; \
	if [ "$$bump" = "dev" ]; then \
	  echo "  effect       publishes this commit to the internal mirror as <next patch>.dev<distance>; NO tag, NO GitHub release"; \
	else \
	  echo "  effect       pushes the next $$bump tag, which triggers build, smoke, mirror publish and a GitHub release"; \
	fi; \
	printf "\nType the bump to confirm: "; \
	read -r reply; \
	if [ "$$reply" != "$$bump" ]; then echo "aborted"; exit 1; fi; \
	$(GH) workflow run $(RELEASE_WORKFLOW) --ref $(RELEASE_BRANCH) -f bump="$$bump"; \
	echo; \
	echo "dispatched. Watch it with:  $(GH) run watch \$$($(GH) run list --workflow $(RELEASE_WORKFLOW) --limit 1 --json databaseId -q '.[0].databaseId')"

release-patch: ## Release a patch version (alias for: make release patch)
	@$(MAKE) --no-print-directory release BUMP=patch

release-minor: ## Release a minor version
	@$(MAKE) --no-print-directory release BUMP=minor

release-major: ## Release a major version
	@$(MAKE) --no-print-directory release BUMP=major

release-dev: ## Publish a dev build of this commit to the mirror (no tag)
	@$(MAKE) --no-print-directory release BUMP=dev

# Reached only as the second goal of `make release <word>`. On its own it is a
# typo for the real target, so say so rather than silently succeeding.
$(_BUMP_WORDS):
	@case " $(MAKECMDGOALS) " in \
	  *" release "*) : ;; \
	  *) echo "make: '$@' is not a target. Did you mean 'make release $@'?"; exit 2 ;; \
	esac
