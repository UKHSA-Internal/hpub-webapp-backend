import os
import sys

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

import psycopg2
from psycopg2 import sql

from configs.get_secret_config import Config

config = Config()


def execute_drop_or_truncate(table_name, connection_params, operation="drop"):
    """
    Executes a DROP TABLE or TRUNCATE TABLE command with CASCADE on the specified table.

    Parameters:
      table_name (str): Name of the table to operate on.
      connection_params (dict): Dictionary with connection parameters (dbname, user, password, host, port).
      operation (str): "drop" to drop the table or "truncate" to delete all rows.
    """
    try:
        # Connect to the PostgreSQL database
        conn = psycopg2.connect(**connection_params)
        conn.autocommit = True  # Necessary to run DDL statements outside transactions
        cur = conn.cursor()

        if operation.lower() == "drop":
            # Drop the table along with any dependent objects
            query = sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                sql.Identifier(table_name)
            )
        elif operation.lower() == "truncate":
            # Delete all rows from the table and cascade to dependent tables
            query = sql.SQL("TRUNCATE TABLE {} CASCADE").format(
                sql.Identifier(table_name)
            )
        else:
            print("Invalid operation. Use 'drop' or 'truncate'.")
            return

        # Execute the query
        cur.execute(query)
        print(
            f"Successfully executed {operation.upper()} on table '{table_name}' with CASCADE."
        )

        # Clean up
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    # Replace these with your actual connection details
    connection_params = {
        "dbname": config.get_db_name(),
        "user": config.get_db_user(),
        "password": config.get_db_password(),
        "host": config.get_db_host(),
        "port": config.get_db_port(),
    }

    # Specify the table you wish to operate on
    table_name = ""  # e.g., "public.users_user"

    # To drop the table entirely (including its schema and dependent objects):
    # execute_drop_or_truncate(table_name, connection_params, operation="drop")

    # Or, to simply clear out all the content (data) of the table while preserving the schema:
    execute_drop_or_truncate(table_name, connection_params, operation="truncate")
