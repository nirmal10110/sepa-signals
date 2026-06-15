"""Logging setup for the mini PC. Call setup_logging() once at process start."""
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: Path | None = None, level: int = logging.INFO,
                  run_name: str = "sepa") -> logging.Logger:
    """Configure root logger: per-run folder + console. Returns the sepa logger.

    Log layout:
        data/logs/{YYYY-MM-DD}/{HH-MM-SS}-{run_name}/sepa.log

    Each invocation of ingest or run_daily gets its own timestamped folder so
    logs are never overwritten and can be committed to git for a full audit trail.
    """
    from . import config as C
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M-%S")
    run_dir = (log_dir or C.DATA_DIR / "logs") / date_str / f"{time_str}-{run_name}"
    run_dir.mkdir(parents=True, exist_ok=True)

    log_file = run_dir / "sepa.log"

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    logging.getLogger("sepa").info("log file: %s", log_file)
    return logging.getLogger("sepa"), run_dir
