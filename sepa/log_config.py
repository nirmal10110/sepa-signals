"""Logging setup for the mini PC. Call setup_logging() once at process start."""
import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO) -> logging.Logger:
    """Configure root logger: rotating file (7 days) + console. Returns the sepa logger."""
    from . import config as C
    log_dir = log_dir or C.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.handlers.TimedRotatingFileHandler(
        log_dir / "sepa.log", when="midnight", backupCount=7, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    return logging.getLogger("sepa")
