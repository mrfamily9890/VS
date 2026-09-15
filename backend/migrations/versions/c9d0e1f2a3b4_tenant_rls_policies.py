"""add database tenant isolation policies

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.exec_driver_sql(
        """
        DO $$
        DECLARE
            tenant_table record;
            policy_name text;
        BEGIN
            FOR tenant_table IN
                SELECT table_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND column_name = 'organization_id'
            LOOP
                policy_name := 'tenant_isolation_' || tenant_table.table_name;
                EXECUTE format('ALTER TABLE %%I ENABLE ROW LEVEL SECURITY', tenant_table.table_name);
                EXECUTE format('DROP POLICY IF EXISTS %%I ON %%I', policy_name, tenant_table.table_name);
                EXECUTE format(
                    'CREATE POLICY %%I ON %%I USING (organization_id = NULLIF(current_setting(''app.organization_id'', true), '''')::integer) WITH CHECK (organization_id = NULLIF(current_setting(''app.organization_id'', true), '''')::integer)',
                    policy_name,
                    tenant_table.table_name
                );
            END LOOP;
        END
        $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    bind.exec_driver_sql(
        """
        DO $$
        DECLARE
            tenant_table record;
            policy_name text;
        BEGIN
            FOR tenant_table IN
                SELECT table_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND column_name = 'organization_id'
            LOOP
                policy_name := 'tenant_isolation_' || tenant_table.table_name;
                EXECUTE format('DROP POLICY IF EXISTS %%I ON %%I', policy_name, tenant_table.table_name);
                EXECUTE format('ALTER TABLE %%I DISABLE ROW LEVEL SECURITY', tenant_table.table_name);
            END LOOP;
        END
        $$;
        """
    )
