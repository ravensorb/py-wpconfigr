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
