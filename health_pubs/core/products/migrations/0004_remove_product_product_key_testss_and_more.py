from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0003_remove_product_product_key_testss"),
    ]

    operations = [
        # Step 1: Create the fields if they do not exist
        migrations.RunSQL(
            sql="""
                ALTER TABLE products_product 
                    ADD COLUMN IF NOT EXISTS product_key_testss varchar(255) DEFAULT '';
                ALTER TABLE products_product 
                    ADD COLUMN IF NOT EXISTS product_key_testsss varchar(255) DEFAULT '';
            """,
            reverse_sql="""
                -- No reverse operation needed for the creation step.
                SELECT 1;
            """,
        ),
        # Step 2: Remove the fields (safely drop even if they are missing)
        migrations.RunSQL(
            sql="""
                ALTER TABLE products_product 
                    DROP COLUMN IF EXISTS product_key_testss;
                ALTER TABLE products_product 
                    DROP COLUMN IF EXISTS product_key_testsss;
            """,
            reverse_sql="""
                -- Reverse not provided as removal is usually irreversible.
                SELECT 1;
            """,
        ),
    ]
