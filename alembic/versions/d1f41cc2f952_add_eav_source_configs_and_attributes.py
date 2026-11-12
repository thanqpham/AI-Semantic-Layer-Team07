"""add-eav-source-configs-and-attributes

Revision ID: d1f41cc2f952
Revises: 62260812bd87
Create Date: 2026-11-11 09:24:43.627225

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1f41cc2f952'
down_revision: str | Sequence[str] | None = '62260812bd87'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drift detected on pre-existing tables by autogenerate was removed on
    # purpose: this migration only adds the EAV tables (AGENTS.md rule).
    op.create_table('eav_source_configs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('semantic_db_id', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('entity_table', sa.String(length=200), nullable=False),
    sa.Column('entity_id_column', sa.String(length=200), nullable=False),
    sa.Column('attribute_mode', sa.String(length=20), nullable=False),
    sa.Column('attribute_column', sa.String(length=200), nullable=True),
    sa.Column('attribute_fk_column', sa.String(length=200), nullable=True),
    sa.Column('dict_table', sa.String(length=200), nullable=True),
    sa.Column('dict_key_column', sa.String(length=200), nullable=True),
    sa.Column('dict_label_column', sa.String(length=200), nullable=True),
    sa.Column('value_columns', sa.JSON(), nullable=False),
    sa.Column('history', sa.JSON(), nullable=True),
    sa.Column('review_status', sa.String(length=20), nullable=False),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("attribute_mode IN ('direct', 'dictionary')", name='ck_eav_source_config_mode'),
    sa.CheckConstraint("review_status IN ('pending_review', 'approved', 'rejected')", name='ck_eav_source_config_review_status'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['semantic_db_id'], ['semantic_databases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('semantic_db_id', 'entity_table', name='uq_eav_source_config_entity_table')
    )
    op.create_table('eav_attributes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('config_id', sa.Integer(), nullable=False),
    sa.Column('attribute_key', sa.String(length=200), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('data_type', sa.String(length=20), nullable=False),
    sa.Column('value_column', sa.String(length=200), nullable=True),
    sa.Column('multi_value_rule', sa.String(length=20), nullable=False),
    sa.Column('history_enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("data_type IN ('string', 'number', 'boolean', 'date', 'datetime')", name='ck_eav_attribute_data_type'),
    sa.CheckConstraint("multi_value_rule IN ('reject', 'first', 'last', 'sum', 'avg', 'min', 'max')", name='ck_eav_attribute_multi_value_rule'),
    sa.ForeignKeyConstraint(['config_id'], ['eav_source_configs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('config_id', 'attribute_key', name='uq_eav_attribute_key')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('eav_attributes')
    op.drop_table('eav_source_configs')
