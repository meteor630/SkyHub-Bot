"""центральная панель управления voice-комнатами + раздельные закрыто/скрыто вместо mode

Revision ID: 0006_voice_panel_lock_hide
Revises: 0005_voice_presets
Create Date: 2026-08-31
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_voice_panel_lock_hide"
down_revision: str | None = "0005_voice_presets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guild_settings",
        sa.Column("voice_control_panel_channel_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "temporary_voice_channels",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "temporary_voice_channels",
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.drop_column("temporary_voice_channels", "mode")


def downgrade() -> None:
    op.add_column(
        "temporary_voice_channels",
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="public"),
    )
    op.drop_column("temporary_voice_channels", "is_hidden")
    op.drop_column("temporary_voice_channels", "is_locked")
    op.drop_column("guild_settings", "voice_control_panel_channel_id")
