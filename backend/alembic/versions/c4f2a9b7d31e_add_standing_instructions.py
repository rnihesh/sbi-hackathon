"""add standing instructions table

Revision ID: c4f2a9b7d31e
Revises: 80916cd8d4fc
Create Date: 2026-07-05 08:10:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f2a9b7d31e'
down_revision: str | None = '80916cd8d4fc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'standing_instructions',
        sa.Column('customer_id', sa.Uuid(), nullable=False),
        sa.Column('from_account_id', sa.Uuid(), nullable=False),
        sa.Column(
            'purpose',
            sa.Enum('goal', 'fd', 'savings', name='standingpurpose', native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column('goal_id', sa.Uuid(), nullable=True),
        sa.Column('amount_paise', sa.BigInteger(), nullable=False),
        sa.Column(
            'cadence',
            sa.Enum('weekly', 'monthly', name='standingcadence', native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column('next_run_date', sa.Date(), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'active', 'paused', 'completed', 'cancelled',
                name='standingstatus', native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('runs_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('amount_paise > 0', name='ck_standing_instructions_amount_positive'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['from_account_id'], ['accounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['goal_id'], ['savings_goals.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_standing_instructions_customer_id'),
        'standing_instructions',
        ['customer_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_standing_instructions_status'),
        'standing_instructions',
        ['status'],
        unique=False,
    )
    op.create_index(
        'ix_standing_instructions_status_next_run',
        'standing_instructions',
        ['status', 'next_run_date'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_standing_instructions_status_next_run', table_name='standing_instructions')
    op.drop_index(op.f('ix_standing_instructions_status'), table_name='standing_instructions')
    op.drop_index(op.f('ix_standing_instructions_customer_id'), table_name='standing_instructions')
    op.drop_table('standing_instructions')
