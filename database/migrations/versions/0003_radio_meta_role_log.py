"""метаданные треков радио и фильтр логирования ролей

Revision ID: 0003_radio_meta_role_log
Revises: 0002_dashboard_and_radio
Create Date: 2026-08-30

Примечание: короткий ID ревизии не случаен -- у Alembic служебная
таблица ``alembic_version.version_num`` по умолчанию ``VARCHAR(32)``,
и более длинное описательное имя туда просто не помещается
(проверено на практике -- см. историю коммитов).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_radio_meta_role_log"
down_revision: str | None = "0002_dashboard_and_radio"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("radio_tracks", sa.Column("artist", sa.String(200), nullable=True))
    op.add_column("radio_tracks", sa.Column("album", sa.String(300), nullable=True))
    op.add_column("radio_tracks", sa.Column("composer", sa.String(200), nullable=True))
    op.add_column("radio_tracks", sa.Column("duration_seconds", sa.Float(), nullable=True))
    op.add_column("radio_tracks", sa.Column("bitrate_kbps", sa.Integer(), nullable=True))
    op.add_column("radio_tracks", sa.Column("cover_path", sa.String(500), nullable=True))

    op.add_column(
        "guild_settings",
        sa.Column("ignored_log_role_ids", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("guild_settings", "ignored_log_role_ids")

    op.drop_column("radio_tracks", "cover_path")
    op.drop_column("radio_tracks", "bitrate_kbps")
    op.drop_column("radio_tracks", "duration_seconds")
    op.drop_column("radio_tracks", "composer")
    op.drop_column("radio_tracks", "album")
    op.drop_column("radio_tracks", "artist")
