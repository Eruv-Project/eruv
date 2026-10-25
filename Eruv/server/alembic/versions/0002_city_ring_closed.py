"""city ring_closed: an open pole line for a pilot

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Existing cities stay closed rings."""
    with op.batch_alter_table('cities') as batch_op:
        batch_op.add_column(sa.Column('ring_closed', sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('cities') as batch_op:
        batch_op.drop_column('ring_closed')
