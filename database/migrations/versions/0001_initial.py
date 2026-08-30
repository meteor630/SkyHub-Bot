"""начальная схема базы данных

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-29
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guilds",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("locale", sa.String(8), nullable=False, server_default="ru"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "guild_settings",
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("welcome_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("moderation_logs_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("deleted_messages_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("edited_messages_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("member_logs_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("error_logs_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("audit_logs_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("status_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("temporary_voice_creator_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("temporary_voice_category_id", sa.BigInteger(), nullable=True),
        sa.Column("moderator_role_id", sa.BigInteger(), nullable=True),
        sa.Column("admin_role_id", sa.BigInteger(), nullable=True),
        sa.Column("support_role_id", sa.BigInteger(), nullable=True),
        sa.Column("owner_role_id", sa.BigInteger(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(200), nullable=False),
        sa.Column("discriminator", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "plugin_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plugin_name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("guild_id", "plugin_name", name="uq_plugin_settings_guild_plugin"),
    )

    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("moderator_id", sa.BigInteger(), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_moderation_actions_guild_target", "moderation_actions", ["guild_id", "target_id"])

    op.create_table(
        "deleted_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("bulk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "edited_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("before", sa.Text(), nullable=False, server_default=""),
        sa.Column("after", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "temporary_voice_channels",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="public"),
        sa.Column("name", sa.String(100), nullable=False, server_default=""),
        sa.Column("member_limit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "voice_channel_owners",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "temp_channel_id",
            sa.BigInteger(),
            sa.ForeignKey("temporary_voice_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("became_owner_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_owner_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_guild_user", "audit_logs", ["guild_id", "user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_guild_user", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("voice_channel_owners")
    op.drop_table("temporary_voice_channels")
    op.drop_table("edited_messages")
    op.drop_table("deleted_messages")
    op.drop_index("ix_moderation_actions_guild_target", table_name="moderation_actions")
    op.drop_table("moderation_actions")
    op.drop_table("plugin_settings")
    op.drop_table("users")
    op.drop_table("guild_settings")
    op.drop_table("guilds")
