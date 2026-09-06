"""приватный форум для сапорта + доп. роли-просмотрщики тикетов

Revision ID: 0007_tickets_forum
Revises: 0006_voice_panel_lock_hide
Create Date: 2026-09-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_tickets_forum"
down_revision: str | None = "0006_voice_panel_lock_hide"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("guild_settings", sa.Column("tickets_forum_channel_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "guild_settings",
        sa.Column("ticket_viewer_role_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("tickets", sa.Column("forum_thread_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "forum_thread_id")
    op.drop_column("guild_settings", "ticket_viewer_role_ids")
    op.drop_column("guild_settings", "tickets_forum_channel_id")
