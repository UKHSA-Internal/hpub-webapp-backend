from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0002_remove_product_product_key_testss_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE products_product
                DROP COLUMN IF EXISTS product_key_testss;
            """,
            reverse_sql="""
                -- Provide reverse SQL if necessary
            """,
        ),
    ]
