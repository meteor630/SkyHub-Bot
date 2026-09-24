"""убрать is_hidden у временных голосовых каналов -- скрытие комнаты убрано целиком

Revision ID: 0008_drop_voice_hidden
Revises: 0007_tickets_forum
Create Date: 2026-09-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_drop_voice_hidden"
down_revision: str | None = "0007_tickets_forum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("temporary_voice_channels", "is_hidden")


def downgrade() -> None:
    op.add_column(
        "temporary_voice_channels",
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
