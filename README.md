# l3io-wp-config

Read and write `define()` constants and `$variable` assignments in a WordPress
`wp-config.php` file.

```python
from l3io.wp.config import MISSING, WpConfigFile

config = WpConfigFile("/www/wp-config.php")

config.get("DB_NAME")                  # 'my_blog'
config.get("WP_DEBUG")                 # False  -- present and falsy
config.get("NOT_THERE") is MISSING     # True   -- absent
config.get_variable("table_prefix")    # 'wp_'  -- a $variable, not a define()

config.set("DB_NAME", "my_blog")       # written, read back, and verified
```

## What this is, and what it is not

This is a reader and writer for the **`define()` subset of PHP that WordPress
itself writes**, plus simple file-scope `$variable` assignments. **It is not a
PHP parser and must not be relied on as one.**

Its scope is deliberately bounded, and the boundaries are these:

- Only **single-quoted** string values are parsed as strings. `define('X', "y")`
  returns the raw text `"y"`, quotes included.
- A value must sit on **one line**. A statement spanning lines is not matched.
- `define()` and `$variable` statements must start at the beginning of a line
  (leading whitespace aside). This is what makes a commented-out
  `// define('X', 'y');` correctly invisible.
- A value that is a **PHP expression** or references another constant is
  returned as its raw source text, not evaluated.
- Adding a constant inserts after the **first** `<?php` opening tag. A file with
  no `<?php\n` cannot have one inserted, and raises `ConfigWriteError`.

Because those limits are real, **every write is verified**. `WpConfigFile.set()`
writes to a temporary file, reads it back, and checks three things before
committing: the constant written carries the value intended, every constant
*not* written is byte-identical, and no key appears twice. On any mismatch it
raises `ReadBackError` and **the original file is left untouched**.

## Install

```shell
pip install l3io-wp-config
```

Requires Python 3.11 or newer. It has **no runtime dependencies**, permanently.

## Absent is not falsy

`get()` and `get_variable()` return the `MISSING` sentinel for a key that is not
defined. A key defined as `false`, `0` or `''` is *present* and falsy. Both are
falsy in a boolean test, so compare identity:

```python
if config.get("WP_DEBUG") is MISSING:
    ...   # not defined at all
```

Values keep the type of the PHP literal: quoted stays `str` (so `'3306'` is the
string `"3306"`, not a number), unquoted `true`/`false` become `bool`, unquoted
integers become `int`, unquoted decimals become `float`.

## Errors

Every failure is a package-owned exception under `WpConfigError`; no `OSError`,
`TypeError` or `ValueError` crosses the public boundary.

| Exception | Raised when |
|---|---|
| `ConfigReadError` | the file cannot be read |
| `ConfigWriteError` | the file cannot be written, or a constant cannot be placed |
| `ConfigValueError` | a value cannot be rendered as a PHP literal |
| `ReadBackError` | verification failed; the file is unchanged |

## Command line

```shell
l3io-wp-config --filename /www/wp-config.php --key DB_NAME --value my_blog
l3io-wp-config --filename /www/wp-config.php --key DB_NAME
```

Also runnable as `python -m l3io.wp.config`. Exit codes are part of the
interface: `0` success, `1` the key is not defined, `2` the operation failed.
A key defined as `false`, `0` or `''` prints its value and exits `0` — that is
what distinguishes it from a key that is absent.

Flags: `--filename`, `--key`, `--value`, `--set-true`, `--set-false`,
`--log-level`.

## Development

```shell
uv sync --locked
make check      # lint, types, architecture contracts, tests
make ci         # replay the whole CI pipeline locally with nektos/act
```

`uv` is pinned by `[tool.uv] required-version` so the lockfile and CI cannot
drift apart. Do not run `uv self update` without changing that pin and CI
together.

## Credits and history

A fork of [`cariad/py-wpconfigr`](https://github.com/cariad/py-wpconfigr) by
Cariad Eccleston, MIT licensed, taken at its 2019 state. The original copyright
notice is retained in `LICENSE`.

Upstream did not stop — it renamed itself and continues as
[`wpconfigger`](https://pypi.org/project/wpconfigger/). **If you want the
original author's maintained package, use `wpconfigger`.** This fork exists
because this project needed to change the parser and did not want to depend on
a package with a single maintainer.

## Changelog

### v1.5.0

- Renamed to `l3io-wp-config`, importing as `l3io.wp.config`.
- `get()` now preserves the PHP literal's type. Previously every numeric-looking
  value, **including quoted ones**, came back as `float` — so an all-digit
  password read back as a number.
- `get()` returns `MISSING` rather than `None` for an absent key, so a falsy
  value is distinguishable from a missing one.
- `set()` behaves identically whether the key exists or not. It previously
  raised `TypeError` for a non-string value only when the key already existed.
- Adding a constant inserts after the first `<?php` tag only. It previously
  inserted at every occurrence.
- The CLI distinguishes a falsy value from an absent key in both output and exit
  code. It previously printed nothing and exited `0` for both.
- `$table_prefix` and other simple file-scope variables can be read and written.
- Every write is verified by reading it back; a failure leaves the file unchanged.
- Errors are package-owned types under `WpConfigError`.
- Packaging moved to `pyproject.toml` with `uv`; Python 3.11+; zero runtime
  dependencies.

### v1.4 - 2018-12-06

- Fixed bug where commented properties were read and updated.

### v1.3 - 2018-12-02

- Added `--set-true` and `--set-false` command-line flags.

### v1.2 - 2018-12-02

- No longer re-writes the configuration file if nothing has changed.

### v1.1 - 2018-12-02

- Added logging.
