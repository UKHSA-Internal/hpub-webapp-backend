from django.db import migrations

# We use CONCURRENTLY -> atomic must be False.
class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        # Make sure this comes after 00xx_unaccent_imm_function
        ("products", "00xx_unaccent_imm_function")
    ]

    operations = [
        migrations.RunSQL(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_products_title_trgm_unaccent
            ON public.products_product
            USING gin (public.unaccent_imm(lower(product_title)) gin_trgm_ops);
            """,
            """
            DROP INDEX CONCURRENTLY IF EXISTS idx_products_title_trgm_unaccent;
            """,
        ),
        migrations.RunSQL(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_products_code_trgm_unaccent
            ON public.products_product
            USING gin (public.unaccent_imm(lower(product_code_no_dashes)) gin_trgm_ops);
            """,
            """
            DROP INDEX CONCURRENTLY IF EXISTS idx_products_code_trgm_unaccent;
            """,
        ),
        migrations.RunSQL(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_products_title_lower_btree
            ON public.products_product (lower(product_title));
            """,
            """
            DROP INDEX CONCURRENTLY IF EXISTS idx_products_title_lower_btree;
            """,
        ),
        migrations.RunSQL(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_products_code_lower_btree
            ON public.products_product (lower(product_code_no_dashes));
            """,
            """
            DROP INDEX CONCURRENTLY IF EXISTS idx_products_code_lower_btree;
            """,
        ),
    ]
