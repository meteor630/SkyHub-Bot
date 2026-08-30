"""доп. каналы-создатели временных voice с фиксированным лимитом (напр. "на 2"/"на 4")

Revision ID: 0005_voice_presets
Revises: 0004_profiles_flights_xp
Create Date: 2026-08-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_voice_presets"
down_revision: str | None = "0004_profiles_flights_xp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guild_settings",
        sa.Column("voice_creator_presets", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("guild_settings", "voice_creator_presets")
