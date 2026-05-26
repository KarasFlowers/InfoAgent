"""add_summaryviewlog

Revision ID: 892f72113d37
Revises: 5668bdccb3e7
Create Date: 2026-05-26 00:03:49.986980

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = '892f72113d37'
down_revision: Union[str, None] = '5668bdccb3e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('summaryviewlog',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('date', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('viewed_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_summaryviewlog_date'), 'summaryviewlog', ['date'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_summaryviewlog_date'), table_name='summaryviewlog')
    op.drop_table('summaryviewlog')
