"""дашборд статуса и радио-плейлист

Revision ID: 0002_dashboard_and_radio
Revises: 0001_initial
Create Date: 2026-08-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_dashboard_and_radio"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("guild_settings", sa.Column("radio_voice_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("guild_settings", sa.Column("radio_text_channel_id", sa.BigInteger(), nullable=True))

    op.create_table(
        "dashboard_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "kind", name="uq_dashboard_messages_guild_kind"),
    )

    op.create_table(
        "radio_tracks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("added_by_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_radio_tracks_guild_position", "radio_tracks", ["guild_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_radio_tracks_guild_position", table_name="radio_tracks")
    op.drop_table("radio_tracks")
    op.drop_table("dashboard_messages")
    op.drop_column("guild_settings", "radio_text_channel_id")
    op.drop_column("guild_settings", "radio_voice_channel_id")
