"""chain links: active flag and created_at

Revision ID: b3c1f2a9d4e7
Revises: 697b01592330
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c1f2a9d4e7'
down_revision: Union[str, Sequence[str], None] = '697b01592330'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('uservictim', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.add_column(sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False, server_default=sa.func.now()))
        batch_op.create_index(batch_op.f('ix_uservictim_active'), ['active'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('uservictim', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_uservictim_active'))
        batch_op.drop_column('created_at')
        batch_op.drop_column('active')
