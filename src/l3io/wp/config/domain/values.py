"""Value types for PHP constants, and the sentinel for an absent key."""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

__all__ = ["MISSING", "ConfigValue", "MissingType"]

#: A PHP constant value as this package represents it.
#:
#: ``str`` covers quoted strings and any literal the parser does not recognise,
#: which it returns as raw source text (see ADR-0010).
ConfigValue: TypeAlias = "str | bool | int | float"


class MissingType:
    """The type of :data:`MISSING`. Not instantiable by callers."""

    _instance: MissingType | None = None

    def __new__(cls) -> MissingType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> Literal[False]:
        return False


#: Returned by ``get()`` when a key is absent.
#:
#: A key whose value is ``false``, ``0`` or ``''`` is present and falsy; an absent
#: key is ``MISSING``. Both are falsy, so test identity -- ``if value is MISSING``
#: -- never truthiness.
MISSING: Final[MissingType] = MissingType()
