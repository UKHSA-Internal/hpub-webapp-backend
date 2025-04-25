from functools import wraps
import logging
from venv import logger
from django.core.cache import caches

logger = logging.getLogger(__name__)


def clear_cache_after(task_func):
    """
    Celery task decorator that clears the default cache
    once the task completes (successfully or not).
    """

    @wraps(task_func)
    def wrapper(*args, **kwargs):
        result = task_func(*args, **kwargs)
        try:
            caches["default"].clear()
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
        return result

    return wrapper
