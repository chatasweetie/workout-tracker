"""Launcher lifecycle checks use temporary data and never stop other servers."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

import macos_launcher as launcher


@pytest.fixture
def environment(tmp_path, monkeypatch):
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        port = connection.getsockname()[1]
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(launcher, "PYTHON", Path(sys.executable))
    monkeypatch.setattr(launcher, "PORT", port)
    launcher.RUNTIME.mkdir()
    return tmp_path


def test_start_reuses_server_and_stop_preserves_data(environment, monkeypatch):
    repo = Path(launcher.__file__).resolve().parent
    database = environment / "workout.db"
    code = f"""
import sys
sys.path.insert(0, {str(repo)!r})
from pathlib import Path
import app
import macos_launcher as launcher
factory = app.create_app
app.create_app = lambda: factory({{"DATABASE": {str(database)!r},
    "BACKUP_DIR": {str(environment / "backups")!r}}})
launcher.ROOT = Path({str(environment)!r})
launcher.PORT = {launcher.PORT}
launcher.run_server(sys.argv[1])
"""
    monkeypatch.setattr(
        launcher, "server_command",
        lambda token: [sys.executable, "-c", code, token],
    )
    # Reap our test child so stop_server can observe its actual exit.
    processes = []
    original_popen = subprocess.Popen

    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        if args and args[0][0] == sys.executable:
            processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", popen)
    original_kill = os.kill

    def kill(pid, sig):
        for process in processes:
            if process.pid == pid:
                process.poll()
        return original_kill(pid, sig)

    monkeypatch.setattr(os, "kill", kill)
    try:
        launcher.start_server()
        state_path = launcher.RUNTIME / "server.json"
        state = json.loads(state_path.read_text())
        assert launcher.launcher_health() == {
            "project": launcher.project_id(), "pid": state["pid"], "token": state["token"],
        }
        before = database.read_bytes()
        launcher.start_server()
        assert json.loads(state_path.read_text()) == state
        assert len(processes) == 1
        launcher.stop_server()
        assert not state_path.exists()
        assert processes[0].poll() is not None
        assert database.read_bytes() == before
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


def test_manual_project_server_is_reused_and_never_stopped(environment, monkeypatch):
    monkeypatch.setattr(launcher, "launcher_health", lambda: None)
    monkeypatch.setattr(launcher, "listener_pids", lambda: [123])
    monkeypatch.setattr(launcher, "is_project_server", lambda pids: pids == [123])
    monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("Must not stop a Terminal server"))
    launcher.start_server()
    launcher.stop_server()
    assert not (launcher.RUNTIME / "server.json").exists()


def test_busy_port_is_reported_without_starting_or_stopping_processes(environment, monkeypatch):
    monkeypatch.setattr(launcher, "launcher_health", lambda: None)
    monkeypatch.setattr(launcher, "listener_pids", lambda: [123])
    monkeypatch.setattr(launcher, "is_project_server", lambda pids: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Must not spawn"))
    monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("Must not kill"))
    with pytest.raises(RuntimeError, match="occupied"):
        launcher.start_server()


def test_stale_pid_is_not_killed_when_ownership_does_not_match(environment, monkeypatch):
    state_path = launcher.RUNTIME / "server.json"
    state_path.write_text(json.dumps({"pid": 123, "token": "old"}))
    monkeypatch.setattr(launcher, "launcher_health", lambda: {
        "project": launcher.project_id(), "pid": 123, "token": "different",
    })
    signals = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(RuntimeError, match="Cannot verify ownership"):
        launcher.stop_server()
    assert signals == [(123, 0)]
    assert state_path.exists()


def test_failed_start_reports_log_and_cleans_ownership_record(environment, monkeypatch):
    monkeypatch.setattr(launcher, "server_command", lambda token: [
        sys.executable, "-c", "raise RuntimeError('test startup failure')",
    ])
    with pytest.raises(RuntimeError, match="server could not start"):
        launcher.start_server()
    assert not (launcher.RUNTIME / "server.json").exists()
    assert "test startup failure" in (launcher.RUNTIME / "server.log").read_text()
