"""ECS container health check for the worker.

Runnable as `python -m app.healthcheck`. Exits 0 when the worker's heartbeat
file (written by app.main.write_heartbeat) is younger than
HEARTBEAT_MAX_AGE_SECONDS, non-zero otherwise.
"""

import os
import sys
import time

from .config import settings


def is_healthy() -> bool:
    try:
        mtime = os.path.getmtime(settings.HEARTBEAT_FILE_PATH)
    except OSError:
        return False

    age = time.time() - mtime
    return age < settings.HEARTBEAT_MAX_AGE_SECONDS


def main() -> int:
    return 0 if is_healthy() else 1


if __name__ == "__main__":
    sys.exit(main())
