"""add rules primary key

Revision ID: 6991bcb18f89
Revises: 94f1cd79b7d4
Create Date: 2024-07-04 14:31:47.752321

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "6991bcb18f89"
down_revision = "49f38c26141c"
branch_labels = None
depends_on = None


# This migration makes ``rules.id`` the primary key and ``rules.name`` a plain
# unique constraint. It has to cope with two different prior states:
#
#   * The historical production state this migration was originally written for,
#     where ``id`` was only UNIQUE (``rules_id_key``) and ``name`` still owned a
#     constraint named ``rules_pkey``.
#   * The state produced by a from-scratch run with current library versions,
#     where ``2745a5bf4c97`` already promoted ``id`` to the primary key (auto
#     named ``rules_pkey1`` because ``rules_pkey`` was taken by the unique on
#     ``name``). Blindly running ``ADD CONSTRAINT rules_pkey PRIMARY KEY (id)``
#     here fails with "multiple primary keys for table rules are not allowed".
#
# The upgrade is therefore written to *converge* on the target schema
# (PK ``rules_pkey`` on ``id``, UNIQUE ``rules_name_key`` on ``name``) regardless
# of which of those states it starts from.

UPGRADE = r"""
DO $$
DECLARE
    pk_name text;
    pk_col  text;
BEGIN
    -- 1. Ensure `name` carries a UNIQUE constraint named rules_name_key.
    --    A leftover unique literally named "rules_pkey" (from 2745a5bf4c97) is
    --    just renamed; otherwise create one if `name` has no unique yet.
    IF EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'rules' AND c.conname = 'rules_pkey' AND c.contype = 'u'
    ) THEN
        ALTER TABLE rules RENAME CONSTRAINT rules_pkey TO rules_name_key;
    ELSIF NOT EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        JOIN unnest(c.conkey) AS k(attnum) ON TRUE
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE t.relname = 'rules' AND c.contype = 'u' AND a.attname = 'name'
    ) THEN
        ALTER TABLE rules ADD CONSTRAINT rules_name_key UNIQUE (name);
    END IF;

    -- 2. Make `id` the primary key, named rules_pkey.
    SELECT c.conname,
           (SELECT a.attname
            FROM unnest(c.conkey) AS k(attnum)
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
            LIMIT 1)
      INTO pk_name, pk_col
    FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
    WHERE t.relname = 'rules' AND c.contype = 'p';

    IF pk_col = 'id' THEN
        -- Already the PK (from-scratch state); just normalise the name.
        IF pk_name <> 'rules_pkey' THEN
            EXECUTE 'ALTER TABLE rules RENAME CONSTRAINT ' || quote_ident(pk_name) || ' TO rules_pkey';
        END IF;
    ELSE
        -- PK is elsewhere (e.g. on `name`) or absent; move it to `id`.
        IF pk_name IS NOT NULL THEN
            EXECUTE 'ALTER TABLE rules DROP CONSTRAINT ' || quote_ident(pk_name);
        END IF;
        ALTER TABLE rules ADD CONSTRAINT rules_pkey PRIMARY KEY (id);
    END IF;

    -- 3. Drop the now-redundant UNIQUE(id) and (re)bind the rule_id foreign key
    --    to `id`. The FK is dropped first because it may currently depend on the
    --    rules_id_key index; recreating it afterwards binds it to the PK instead.
    ALTER TABLE package_rules DROP CONSTRAINT IF EXISTS package_rules_rule_id_fkey;

    IF EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'rules' AND c.conname = 'rules_id_key'
    ) THEN
        ALTER TABLE rules DROP CONSTRAINT rules_id_key;
    END IF;

    ALTER TABLE package_rules
        ADD CONSTRAINT package_rules_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES rules(id);
END $$;
"""

DOWNGRADE = r"""
DO $$
BEGIN
    -- Reverse to the pre-upgrade shape: `id` UNIQUE (not PK), `name` owning a
    -- constraint named rules_pkey. Guarded so it is safe from either final state.
    ALTER TABLE package_rules DROP CONSTRAINT IF EXISTS package_rules_rule_id_fkey;

    IF EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        JOIN unnest(c.conkey) AS k(attnum) ON TRUE
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE t.relname = 'rules' AND c.contype = 'p' AND a.attname = 'id'
    ) THEN
        ALTER TABLE rules DROP CONSTRAINT rules_pkey;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'rules' AND c.conname = 'rules_id_key'
    ) THEN
        ALTER TABLE rules ADD CONSTRAINT rules_id_key UNIQUE (id);
    END IF;

    ALTER TABLE package_rules
        ADD CONSTRAINT package_rules_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES rules(id);

    IF EXISTS (
        SELECT 1 FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'rules' AND c.conname = 'rules_name_key'
    ) THEN
        ALTER TABLE rules RENAME CONSTRAINT rules_name_key TO rules_pkey;
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
