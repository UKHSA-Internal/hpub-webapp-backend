import os
import logging


def get_logger(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    return logger
