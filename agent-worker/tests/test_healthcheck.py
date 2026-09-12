import os
import time

from app import healthcheck
from app import main as worker


def test_is_healthy_true_for_fresh_heartbeat(tmp_path, monkeypatch):
    heartbeat_file = tmp_path / "heartbeat"
    heartbeat_file.write_text(str(time.time()))

    monkeypatch.setattr(
        healthcheck.settings, "HEARTBEAT_FILE_PATH", str(heartbeat_file)
    )
    monkeypatch.setattr(healthcheck.settings, "HEARTBEAT_MAX_AGE_SECONDS", 1200)

    assert healthcheck.is_healthy() is True
    assert healthcheck.main() == 0


def test_is_healthy_false_for_stale_heartbeat(tmp_path, monkeypatch):
    heartbeat_file = tmp_path / "heartbeat"
    heartbeat_file.write_text(str(time.time()))
    stale_time = time.time() - 2000
    os.utime(heartbeat_file, (stale_time, stale_time))

    monkeypatch.setattr(
        healthcheck.settings, "HEARTBEAT_FILE_PATH", str(heartbeat_file)
    )
    monkeypatch.setattr(healthcheck.settings, "HEARTBEAT_MAX_AGE_SECONDS", 1200)

    assert healthcheck.is_healthy() is False
    assert healthcheck.main() == 1


def test_is_healthy_false_when_heartbeat_file_missing(tmp_path, monkeypatch):
    missing_file = tmp_path / "does-not-exist"

    monkeypatch.setattr(healthcheck.settings, "HEARTBEAT_FILE_PATH", str(missing_file))

    assert healthcheck.is_healthy() is False
    assert healthcheck.main() == 1


def test_write_heartbeat_writes_a_fresh_timestamp(tmp_path, monkeypatch):
    heartbeat_file = tmp_path / "heartbeat"
    monkeypatch.setattr(worker.settings, "HEARTBEAT_FILE_PATH", str(heartbeat_file))

    before = time.time()
    worker.write_heartbeat()
    after = time.time()

    written = float(heartbeat_file.read_text())
    assert before <= written <= after
