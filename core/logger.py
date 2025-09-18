# -*- coding: utf-8 -*-
import logging, os
from typing import Optional


def setup_logger(level: str = "INFO", logfile: Optional[str] = None):
    lvl = getattr(logging, level.upper(), logging.INFO)
    fmt = '[%(asctime)s] %(levelname)s: %(message)s'
    logging.basicConfig(level=lvl, format=fmt)
    if logfile:
        os.makedirs(os.path.dirname(logfile), exist_ok=True)
        fh = logging.FileHandler(logfile, encoding='utf-8')
        fh.setLevel(lvl); fh.setFormatter(logging.Formatter(fmt))
        logging.getLogger().addHandler(fh)
