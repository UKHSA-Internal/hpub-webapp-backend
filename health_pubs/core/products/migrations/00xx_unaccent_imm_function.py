from django.db import migrations

# Creates an immutable wrapper around the unaccent() dictionary
# so we can use it in expression indexes and with TrigramSimilarity.
CREATE_FUNC_SQL = r"""
DO $$
BEGIN
  -- Only create the wrapper if the unaccent extension exists
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'unaccent') THEN
    CREATE OR REPLACE FUNCTION public.unaccent_imm(text)
    RETURNS text
    LANGUAGE sql
    IMMUTABLE
    PARALLEL SAFE
    AS $$
      SELECT unaccent('public.unaccent', $1)
    $$;
    COMMENT ON FUNCTION public.unaccent_imm(text) IS
      'Immutable wrapper for unaccent(text) using the public.unaccent dictionary';
  ELSE
    RAISE NOTICE 'Extension "unaccent" not installed; skipping unaccent_imm creation.';
  END IF;
END$$;
"""

DROP_FUNC_SQL = "DROP FUNCTION IF EXISTS public.unaccent_imm(text);"


class Migration(migrations.Migration):
    atomic = True  # safe; no CONCURRENTLY here
    dependencies = [
        # put your last migration here, e.g. ("products", "00xx_previous")
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_FUNC_SQL, reverse_sql=DROP_FUNC_SQL),
    ]
