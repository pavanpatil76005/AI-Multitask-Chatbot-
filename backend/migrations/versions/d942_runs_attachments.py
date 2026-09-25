"""Persist task run lifecycle and attachment ownership."""
from alembic import op
import sqlalchemy as sa

revision = "d942_runs_attachments"
down_revision = "c831_task_results"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("task_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("generation_token", sa.String(36)),
        sa.Column("deadline_at", sa.DateTime()),
        sa.Column("user_message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("result_message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    op.create_index("ix_task_runs_chat_id", "task_runs", ["chat_id"])
    op.add_column("tasks", sa.Column("run_id", sa.Integer(), sa.ForeignKey("task_runs.id", ondelete="CASCADE")))
    op.add_column("tasks", sa.Column("generation_token", sa.String(36)))
    op.create_index("ix_tasks_run_id", "tasks", ["run_id"])
    op.execute("UPDATE tasks SET status='failed', error='Previous execution interrupted. Retry this task.' WHERE status IN ('in_progress', 'running')")
    op.execute("UPDATE tasks SET status='completed' WHERE status='done'")
    op.create_table("attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id", ondelete="CASCADE")),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_attachments_user_id", "attachments", ["user_id"])
    op.create_index("ix_attachments_chat_id", "attachments", ["chat_id"])


def downgrade():
    op.drop_table("attachments")
    op.drop_index("ix_tasks_run_id", table_name="tasks")
    op.drop_column("tasks", "run_id")
    op.drop_column("tasks", "generation_token")
    op.drop_table("task_runs")
