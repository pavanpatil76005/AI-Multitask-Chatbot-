"""Classify exact legacy provider failure placeholders as failed responses.

Content is preserved for auditability. Downgrade does not turn failures back into
successful answers because their original status cannot safely be inferred.
"""
from alembic import op
import sqlalchemy as sa

revision = "i405_legacy_failures"
down_revision = "h304_generation_start"
branch_labels = None
depends_on = None


def upgrade():
    placeholders = [
        f"I couldn{apostrophe}t generate a reply right now.{suffix}"
        for apostrophe in ("'", "\u2019", "\ufffd")
        for suffix in ("", " Please try again in a moment.",
                       "\nPlease try again in a moment.", "\n\nPlease try again in a moment.")
    ]
    messages = sa.table("messages", sa.column("role"), sa.column("content"),
                        sa.column("status"), sa.column("generation_token"))
    op.execute(messages.update().where(
        messages.c.role == "assistant", messages.c.status == "completed",
        sa.func.trim(messages.c.content).in_(placeholders),
    ).values(status="failed", generation_token=None))


def downgrade():
    pass
