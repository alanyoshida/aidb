"""Catálogo de provedores de LLM: tabela + seed dos presets.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-02 22:10:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None

_PRESETS = [
    {
        "id": "glm", "label": "GLM (Z.ai)", "kind": "native", "provider_id": "zhipuai",
        "base_url": None, "env_name": "ZHIPU_API_KEY", "models": ["glm-4.6"], "is_preset": True,
    },
    {
        "id": "anthropic", "label": "Anthropic", "kind": "native", "provider_id": "anthropic",
        "base_url": None, "env_name": "ANTHROPIC_API_KEY",
        "models": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest"], "is_preset": True,
    },
    {
        "id": "openai", "label": "OpenAI", "kind": "native", "provider_id": "openai",
        "base_url": None, "env_name": "OPENAI_API_KEY",
        "models": ["gpt-4o", "gpt-4o-mini"], "is_preset": True,
    },
    {
        "id": "openrouter", "label": "OpenRouter", "kind": "native", "provider_id": "openrouter",
        "base_url": None, "env_name": "OPENROUTER_API_KEY", "models": [], "is_preset": True,
    },
]


def upgrade() -> None:
    table = op.create_table(
        'llm_provider',
        sa.Column('id', sa.String(40), nullable=False),
        sa.Column('label', sa.String(120), nullable=False),
        sa.Column('kind', sa.String(30), nullable=False, server_default='openai-compatible'),
        sa.Column('provider_id', sa.String(60), nullable=False),
        sa.Column('base_url', sa.String(255), nullable=True),
        sa.Column('env_name', sa.String(60), nullable=False, server_default=''),
        sa.Column('models', postgresql.JSON(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('is_preset', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.bulk_insert(table, _PRESETS)


def downgrade() -> None:
    op.drop_table('llm_provider')