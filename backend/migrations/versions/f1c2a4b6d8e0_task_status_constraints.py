"""Enforce canonical task and run states."""
from alembic import op

revision = "f1c2a4b6d8e0"
down_revision = "d942_runs_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE tasks SET status = 'completed' WHERE status = 'done'")
    op.execute(
        "UPDATE tasks SET status = 'failed', progress = 0, "
        "error = COALESCE(NULLIF(error, ''), 'Legacy task state was invalid; retry this task.') "
        "WHERE status NOT IN ('pending', 'running', 'completed', 'failed', 'cancelled')"
    )
    op.execute(
        "UPDATE task_runs SET status = 'failed', deadline_at = NULL, generation_token = NULL "
        "WHERE status NOT IN ('pending', 'running', 'completed', 'failed', 'cancelled')"
    )
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_task_runs_status",
        "task_runs",
        "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_task_runs_status", "task_runs", type_="check")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")