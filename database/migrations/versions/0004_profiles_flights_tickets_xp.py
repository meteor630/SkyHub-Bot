"""авиапрофиль, бортжурнал, вылеты сообщества, тикеты, XP/репутация

Revision ID: 0004_profiles_flights_xp
Revises: 0003_radio_meta_role_log
Create Date: 2026-08-30

Реализует блок функций из ТЗ §41 ("не обязательно реализовывать всё
сразу") и заметки клиента про "систему контекста пользователя".
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_profiles_flights_xp"
down_revision: str | None = "0003_radio_meta_role_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("guild_settings", sa.Column("flight_log_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("guild_settings", sa.Column("tickets_category_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "guild_settings",
        sa.Column("profile_role_ids", sa.JSON(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "user_profiles",
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("role_type", sa.String(30), nullable=False),
        sa.Column("simulator", sa.String(30), nullable=True),
        sa.Column("network", sa.String(30), nullable=True),
        sa.Column("vatsim_id", sa.String(30), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "flight_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("aircraft", sa.String(100), nullable=False),
        sa.Column("departure_icao", sa.String(10), nullable=False),
        sa.Column("arrival_icao", sa.String(10), nullable=False),
        sa.Column("flight_minutes", sa.Integer(), nullable=False),
        sa.Column("network", sa.String(30), nullable=True),
        sa.Column("vatsim_id", sa.String(30), nullable=True),
        sa.Column("remarks", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_flight_logs_guild_user", "flight_logs", ["guild_id", "user_id"])

    op.create_table(
        "flight_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("route", sa.String(100), nullable=False),
        sa.Column("aircraft", sa.String(100), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_participants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "flight_event_participants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("flight_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_flight_event_participants_event", "flight_event_participants", ["event_id"])

    op.create_table(
        "tickets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("creator_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "user_stats",
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flight_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reputation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_stats")
    op.drop_table("tickets")
    op.drop_index("ix_flight_event_participants_event", table_name="flight_event_participants")
    op.drop_table("flight_event_participants")
    op.drop_table("flight_events")
    op.drop_index("ix_flight_logs_guild_user", table_name="flight_logs")
    op.drop_table("flight_logs")
    op.drop_table("user_profiles")

    op.drop_column("guild_settings", "profile_role_ids")
    op.drop_column("guild_settings", "tickets_category_id")
    op.drop_column("guild_settings", "flight_log_channel_id")
