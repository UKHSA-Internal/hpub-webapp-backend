from functools import wraps
from venv import logger
from django.db import connection
import logging

logger = logging.getLogger(__name__)


def singleton_cron(lock_id: int):
    """
    Ensures only one instance of the decorated function runs at a time
    by acquiring a PostgreSQL advisory lock.

    :param lock_id: Unique integer ID for the lock (should be stable per task)
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            acquired = False
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s);", [lock_id])
                    acquired = cursor.fetchone()[0]

                if acquired:
                    return func(*args, **kwargs)
                else:
                    logger.info(
                        f"Skipped {func.__name__}: lock already acquired elsewhere."
                    )
            finally:
                if acquired:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s);", [lock_id])

        return wrapper

    return decorator
