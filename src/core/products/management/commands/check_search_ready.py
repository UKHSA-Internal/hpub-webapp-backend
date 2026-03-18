from django.core.management.base import BaseCommand, CommandError
from django.db import connection

REQUIRED_EXTS = {"unaccent", "pg_trgm"}
REQUIRED_INDEXES = {
    "idx_products_title_trgm_unaccent",
    "idx_products_code_trgm_unaccent",
    "idx_products_title_lower_btree",
    "idx_products_code_lower_btree",
}


class Command(BaseCommand):
    help = (
        "Verify unaccent/pg_trgm extensions, unaccent_imm(), and search indexes exist."
    )

    def handle(self, *args, **opts):
        with connection.cursor() as cur:
            # Extensions
            cur.execute("SELECT extname FROM pg_extension;")
            exts = {row[0] for row in cur.fetchall()}
            missing_exts = REQUIRED_EXTS - exts

            # Function
            cur.execute(
                """
                SELECT 1
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public'
                  AND p.proname = 'unaccent_imm'
                  AND pg_get_function_identity_arguments(p.oid) = 'text';
            """
            )
            has_func = bool(cur.fetchone())

            # Indexes
            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                  AND tablename = 'products_product';
            """
            )
            present_indexes = {row[0] for row in cur.fetchall()}
            missing_indexes = REQUIRED_INDEXES - present_indexes

        errors = []
        if missing_exts:
            errors.append(f"Missing extensions: {', '.join(sorted(missing_exts))}")
        if not has_func:
            errors.append("Missing function: public.unaccent_imm(text)")
        if missing_indexes:
            errors.append(f"Missing indexes: {', '.join(sorted(missing_indexes))}")

        if errors:
            raise CommandError("; ".join(errors))

        self.stdout.write(self.style.SUCCESS("Search stack ready."))
