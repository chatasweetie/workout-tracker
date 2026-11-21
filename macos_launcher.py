"""Install and run the macOS desktop launcher without a Terminal window."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / ".venv" / "bin" / "python"
RUNTIME = ROOT / ".desktop-launcher"
PORT = 5001


def project_id():
    return hashlib.sha256(str(ROOT).encode()).hexdigest()


def url():
    return f"http://127.0.0.1:{PORT}"


def health(path):
    try:
        with build_opener(ProxyHandler({})).open(url() + path, timeout=0.5) as response:
            return json.load(response)
    except (URLError, TimeoutError, json.JSONDecodeError):
        return None


def launcher_health():
    result = health("/desktop-health")
    if isinstance(result, dict) and result.get("project") == project_id():
        return result
    return None


def listener_pids():
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-t", f"-iTCP:{PORT}", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    )
    if result.returncode not in (0, 1) or result.stderr:
        raise RuntimeError(f"Could not check port {PORT}: {result.stderr.strip()}")
    return sorted({int(pid) for pid in result.stdout.split()})


def is_project_server(pids):
    result = subprocess.run(
        ["/usr/sbin/lsof", "-a", "-p", ",".join(map(str, pids)), "-d", "cwd", "-Fn"],
        capture_output=True, text=True, check=True,
    )
    directories = [line[1:] for line in result.stdout.splitlines() if line.startswith("n")]
    return (
        len(directories) == len(pids)
        and all(Path(directory).resolve() == ROOT for directory in directories)
        and health("/health") == {"status": "ok"}
    )


def server_command(token):
    return [str(PYTHON), str(Path(__file__).resolve()), "--serve", token]


def start_server():
    if launcher_health() is not None:
        return
    pids = listener_pids()
    if pids:
        if is_project_server(pids):
            return
        raise RuntimeError(
            f"Port {PORT} is occupied by another or unresponsive app. "
            "Stop that app and try again; no process was stopped."
        )
    if not PYTHON.is_file():
        raise RuntimeError("The project's .venv is missing. Follow the README setup first.")

    token = secrets.token_hex(16)
    state_path = RUNTIME / "server.json"
    log_path = RUNTIME / "server.log"
    with log_path.open("a") as log:
        process = subprocess.Popen(
            server_command(token), cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    ready = False
    try:
        state_path.write_text(json.dumps({"pid": process.pid, "token": token}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"The server could not start. See {log_path}")
            result = launcher_health()
            if result and result.get("token") == token and result.get("pid") == process.pid:
                ready = True
                return
            time.sleep(0.2)
        raise RuntimeError(f"The server did not become ready within 20 seconds. See {log_path}")
    finally:
        if not ready:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            state_path.unlink(missing_ok=True)


def stop_server():
    state_path = RUNTIME / "server.json"
    if not state_path.exists():
        print("No launcher-owned server to stop; any Terminal server is left running.")
        return
    state = json.loads(state_path.read_text())
    pid = state.get("pid")
    token = state.get("token")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0 or not isinstance(token, str):
        raise ValueError(f"Invalid launcher ownership record: {state_path}")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        state_path.unlink()
        print("The launcher server has already stopped.")
        return
    result = launcher_health()
    if not result or result.get("pid") != pid or result.get("token") != token:
        raise RuntimeError(
            f"Cannot verify ownership of process {pid}; no process was stopped. "
            f"Check {RUNTIME / 'server.log'}."
        )
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            state_path.unlink()
            return
        time.sleep(0.1)
    raise RuntimeError(f"Process {pid} has not exited after 10 seconds. No force-kill was attempted.")


def run_server(token):
    from app import create_app

    application = create_app()

    @application.get("/desktop-health")
    def desktop_health():
        return {"project": project_id(), "pid": os.getpid(), "token": token}

    application.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)


def install():
    destination = Path.home() / "Desktop" / "Workout Tracker.app"
    if destination.exists():
        raise FileExistsError(f"{destination} already exists. Move it aside before reinstalling.")
    command = shlex.join([str(PYTHON), str(Path(__file__).resolve())])
    script = f"""
property launcherCommand : {json.dumps(command)}

on run
    openTracker()
end run

on reopen
    openTracker()
end reopen

on openTracker()
    try
        do shell script launcherCommand
    on error errorMessage
        display alert "Workout Tracker could not open" message errorMessage as critical
        quit
    end try
end openTracker

on quit
    try
        do shell script launcherCommand & " --stop"
    on error errorMessage
        display alert "Workout Tracker could not stop its server" message errorMessage as critical
    end try
    continue quit
end quit
"""
    subprocess.run(["/usr/bin/osacompile", "-s", "-o", str(destination), "-e", script], check=True)
    print(f"Installed {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--install", action="store_true")
    options.add_argument("--stop", action="store_true")
    options.add_argument("--serve", metavar="TOKEN")
    args = parser.parse_args()
    try:
        if args.install:
            install()
        elif args.serve:
            run_server(args.serve)
        else:
            RUNTIME.mkdir(mode=0o700, exist_ok=True)
            with (RUNTIME / "lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if args.stop:
                    stop_server()
                else:
                    start_server()
                    subprocess.run(["/usr/bin/open", url()], check=True)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Workout Tracker: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
