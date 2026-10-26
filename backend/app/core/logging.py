from __future__ import annotations

import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    if logging.getLogger("ingenia").handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger = logging.getLogger("ingenia")
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"ingenia.{name}")
