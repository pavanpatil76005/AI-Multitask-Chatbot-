"""Track the start of each generation independently of message creation."""
from alembic import op
import sqlalchemy as sa

revision = "h304_generation_start"
down_revision = "g203_task_in_progress"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("generation_started_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE messages SET generation_started_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE status='generating'")


def downgrade():
    op.drop_column("messages", "generation_started_at")
