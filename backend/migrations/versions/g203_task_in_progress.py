"""Use the public in_progress name for individual task execution."""
from alembic import op

revision = "g203_task_in_progress"
down_revision = "f1c2a4b6d8e0"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.execute("UPDATE tasks SET status='in_progress' WHERE status='running'")
    op.create_check_constraint("ck_tasks_status", "tasks",
        "status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled')")


def downgrade():
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.execute("UPDATE tasks SET status='running' WHERE status='in_progress'")
    op.create_check_constraint("ck_tasks_status", "tasks",
        "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')")
