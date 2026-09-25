"""Track response attempts without modifying the separate task migration."""
from alembic import op
import sqlalchemy as sa
revision = "b72f100c1020"
down_revision = "63abf2568aaf"
branch_labels = ("chat_recovery",)
depends_on = None

def upgrade():
    op.add_column("messages", sa.Column("generation_token", sa.String(36), nullable=True))

def downgrade():
    op.drop_column("messages", "generation_token")
