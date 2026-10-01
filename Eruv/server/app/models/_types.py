"""Portable enum column helper shared by the models."""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum


def str_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """Store a StrEnum by value as a VARCHAR with a CHECK constraint (no native DB enum)."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )
