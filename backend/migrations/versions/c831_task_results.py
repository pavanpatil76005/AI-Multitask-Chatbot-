"""Merge recovery/task branches and persist task results."""
from alembic import op
import sqlalchemy as sa

revision = "c831_task_results"
down_revision = ("a69d90b17567", "b72f100c1020")
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("result", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("error", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("tasks", "error")
    op.drop_column("tasks", "result")
