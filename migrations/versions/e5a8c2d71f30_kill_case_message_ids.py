"""kill case message ids

Revision ID: e5a8c2d71f30
Revises: ac7bbdf3b94d
Create Date: 2026-10-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a8c2d71f30'
down_revision: Union[str, Sequence[str], None] = 'ac7bbdf3b94d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('killcase', schema=None) as batch_op:
        batch_op.add_column(sa.Column('org_message_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('org_message_is_photo', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('victim_message_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('killcase', schema=None) as batch_op:
        batch_op.drop_column('victim_message_id')
        batch_op.drop_column('org_message_is_photo')
        batch_op.drop_column('org_message_id')
