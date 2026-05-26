"""LUCA-flow runner.

One-command driver. Spawns relay + planner + validator as subprocesses,
waits for Phoenix + every peer to be healthy, runs the orchestrator
inline (which spawns workers and the deployer), tears everything down,
prints a summary, exits non-zero if the flow had unexpected outcomes.

This is what `make luca-demo` calls.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from luca import deployer as deployer_mod
from luca.orchestrator import run_flow

DEFAULT_RELAY_PORT = 8080
DEFAULT_PLANNER_PORT = 9101
DEFAULT_VALIDATOR_PORT = 9102


def _wait_healthy(url: str, name: str, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_err: str = ""
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=1.5)
            if r.status_code == 200:
                return
        except httpx.HTTPError as e:
            last_err = str(e)
        time.sleep(0.2)
    raise RuntimeError(f"{name} did not become healthy at {url} (last_err={last_err!r})")


def _kill(p: subprocess.Popen[bytes] | None) -> None:
    if p is None or p.poll() is not None:
        return
    try:
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=3.0)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--root",
        # The luca package lives at examples/luca-flow/src/luca/, so the
        # demo's project root is two levels up from this file.
        default=str(Path(__file__).resolve().parents[2]),
        help="examples/luca-flow root",
    )
    # Backend-agnostic OTLP endpoint. Defaults to env var or Phoenix's local
    # port, but anything OTLP/HTTP works (Tempo on 4318, Honeycomb, ...).
    default_collector = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:6006")
    p.add_argument(
        "--collector",
        default=default_collector,
        help=(
            "OTLP/HTTP collector endpoint to export spans to. "
            "Defaults to $OTEL_EXPORTER_OTLP_ENDPOINT or Phoenix's local port."
        ),
    )
    p.add_argument(
        "--require-collector",
        action="store_true",
        default=True,
        help="Probe `<collector>/healthz` (or `/ready`) before booting peers. "
        "Default on so misconfigurations fail loud.",
    )
    p.add_argument(
        "--no-require-collector",
        dest="require_collector",
        action="store_false",
    )
    args = p.parse_args()

    root = Path(args.root).resolve()
    if not (root / "spec.yaml").exists():
        print(f"❌ no spec.yaml at {root}", file=sys.stderr)
        return 2

    # Three-pass collector probe: Phoenix /healthz, Tempo /ready, TCP connect.
    if args.require_collector:
        ok = False
        probe_label = ""
        for probe_path in ("/healthz", "/ready"):
            try:
                r = httpx.get(f"{args.collector}{probe_path}", timeout=2.0)
                if r.status_code == 200:
                    ok = True
                    probe_label = probe_path
                    break
            except httpx.HTTPError:
                continue
        if not ok:
            parsed = urlparse(args.collector)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            try:
                with socket.create_connection((host, port), timeout=2.0):
                    ok = True
                    probe_label = f"tcp:{host}:{port}"
            except OSError:
                pass
        if ok:
            print(f"📡 Collector is up at {args.collector} ({probe_label})")
        else:
            print(
                f"❌ No OTLP collector reachable at {args.collector}. "
                "Start one (Phoenix: `phoenix serve`; Tempo: `make tempo-up`) "
                "or pass --no-require-collector.",
                file=sys.stderr,
            )
            return 3

    # Tear down stale runs.
    stage = root / ".luca-stage"
    if stage.exists():
        shutil.rmtree(stage)
    dist = root / "dist"
    if dist.exists():
        for child in dist.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    relay_url = f"http://127.0.0.1:{DEFAULT_RELAY_PORT}"

    # Env shared by all subprocesses.
    env = os.environ.copy()
    env["OTEL_EXPORTER_OTLP_ENDPOINT"] = args.collector
    env["OTEL_A2A_RELAY_STAR_ENFORCE"] = "1"
    # Start with empty peer registry; the LUCA processes register dynamically.
    env["OTEL_A2A_RELAY_PEERS"] = ""

    procs: list[tuple[str, subprocess.Popen[bytes]]] = []

    def _spawn(name: str, args_list: list[str]) -> subprocess.Popen[bytes]:
        log_dir = Path(__file__).resolve().parents[4] / "logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"luca-{name}.log"
        f = open(log_path, "w")
        proc = subprocess.Popen[bytes](args_list, env=env, stdout=f, stderr=subprocess.STDOUT)
        procs.append((name, proc))
        print(f"  → spawned {name} (pid {proc.pid}); log: {log_path}")
        return proc

    print("🚀 Bringing up LUCA-flow processes...")
    try:
        _spawn(
            "relay",
            [
                "uv",
                "run",
                "uvicorn",
                "otel_a2a_relay_core.server:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(DEFAULT_RELAY_PORT),
            ],
        )
        _wait_healthy(f"{relay_url}/healthz", "relay")

        _spawn(
            "planner",
            [
                "uv",
                "run",
                "python",
                "-m",
                "luca.planner",
                "--script",
                str(root / "script.yaml"),
                "--port",
                str(DEFAULT_PLANNER_PORT),
                "--relay",
                relay_url,
            ],
        )
        _wait_healthy(f"http://127.0.0.1:{DEFAULT_PLANNER_PORT}/healthz", "planner")

        _spawn(
            "validator",
            [
                "uv",
                "run",
                "python",
                "-m",
                "luca.validator",
                "--port",
                str(DEFAULT_VALIDATOR_PORT),
                "--relay",
                relay_url,
            ],
        )
        _wait_healthy(f"http://127.0.0.1:{DEFAULT_VALIDATOR_PORT}/healthz", "validator")

        # Run the orchestrator inline.
        print("🎯 Director: starting flow")
        state = run_flow(
            spec_path=root / "spec.yaml",
            script_path=root / "script.yaml",
            project_root=root,
            relay_url=relay_url + "/",
        )

        # Run the deployer.
        print("📦 Release Manager: assembling dist/")
        result = deployer_mod.deploy(
            project_root=root,
            stage_dir=root / ".luca-stage",
            assets_dir=root / "assets",
            citations_md_path=root / "CITATIONS.md",
            sources_yaml_path=root / "assets" / "img" / "nasa" / "SOURCES.yaml",
            spec_path=root / "spec.yaml",
            dist_dir=root / "dist",
        )
        print(f"📦 Release Manager: deployed {len(result['pages'])} pages to {result['dist_dir']}")

        # Acceptance summary
        accepted = [o for o in state.outcomes if o["outcome"] == "accepted"]
        crashed = [o for o in state.outcomes if o["outcome"] == "crashed"]
        needs_followup = [o for o in state.outcomes if o["outcome"] == "needs-followup"]
        rogue = [o for o in state.outcomes if o["outcome"] == "rogue-rejected"]
        print()
        print("=" * 72)
        print("AURORA flow result")
        print("=" * 72)
        print(f"  ✅ accepted        : {len(accepted)}")
        print(f"  🔁 needs-followup  : {len(needs_followup)}")
        print(f"  💥 crashed         : {len(crashed)}  (expected: 1, worker-d)")
        print(f"  🛑 rogue-rejected  : {len(rogue)}    (expected: 1, worker-g)")
        print(f"  📦 dist files      : {len(list((root / 'dist').glob('*.html')))} HTML pages")
        print(f"  📨 trace events    : {len(state.trace)}")
        print()
        # Acceptance guard: expect at least 1 crashed (d), 1 rogue (g), 1 followup (b),
        # and the rest accepted. If not, exit non-zero.
        ok = (
            len(crashed) >= 1
            and len(rogue) >= 1
            and len(needs_followup) >= 1
            and len(accepted) >= 5  # a, c, e, f, h at minimum
        )
        if not ok:
            print("❌ flow outcomes did not match expected shape", file=sys.stderr)
            return 4
        print("✅ flow shape matches expectations")
        return 0
    finally:
        print("🧹 Tearing down LUCA-flow processes...")
        for name, proc in reversed(procs):
            print(f"  → stopping {name}")
            _kill(proc)


if __name__ == "__main__":
    sys.exit(main())
