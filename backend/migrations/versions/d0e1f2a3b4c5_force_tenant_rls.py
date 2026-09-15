"""force tenant isolation for database roles"""

from typing import Sequence, Union

from alembic import op


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
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
        BEGIN
            FOR tenant_table IN
                SELECT table_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND column_name = 'organization_id'
            LOOP
                EXECUTE format('ALTER TABLE %%I FORCE ROW LEVEL SECURITY', tenant_table.table_name);
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
        BEGIN
            FOR tenant_table IN
                SELECT table_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND column_name = 'organization_id'
            LOOP
                EXECUTE format('ALTER TABLE %%I NO FORCE ROW LEVEL SECURITY', tenant_table.table_name);
            END LOOP;
        END
        $$;
        """
    )
