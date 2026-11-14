#!/usr/bin/env python3
"""Comparison experiment: B0 naive · B1 request_id · B2 args_hash · Full, under identical faults (stdlib only).

    docker compose -f docker-compose.yml -f eval/compose.experiment.yml up -d --build
    python3 eval/run_experiment.py --reps 5          # → eval/results/<timestamp>.jsonl
    uv run --with matplotlib python eval/report.py   # → eval/report.md + eval/ivr.png

This script plays the DEVICE. Per mode it differs only in how it keys retries:
  naive        a NEW key for every submission (what a client without an outbox does)
  others       one key per step, persisted across retries (outbox)
Everything behind hop ① is the real stack; the agent picks its behaviour from `experimentMode`.

Ground truth is the mocks' per-episode trace count, never what the gateway or agent report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, timedelta
from pathlib import Path

GATEWAY = "http://127.0.0.1:18081"
MOCKS = "http://127.0.0.1:9100"
TOXIPROXY = "http://127.0.0.1:8474"

MODES = ["naive", "request_id", "args_hash", "full"]
FAULTS = ["none", "hop1_offline", "hop1_lost_response", "hop2_lost_response", "hop3_down", "hop3_lost_response"]
STALE = {"slot_taken": "book_appointment", "expired": "notify_family",
         "tool_changed": "book_appointment", "still_valid": "book_appointment"}
TOOLS = ["book_appointment", "notify_family"]
TERMINAL = {"DONE", "NEEDS_USER", "FAILED", "CANCELLED"}

CLIENT_TIMEOUT_S = 3.0      # device → gateway
BUDGET_S = 25.0             # per episode
POLL_S = 0.4
OFFLINE_S = 2.0             # hop1_offline: how long the device has no network


class NetError(Exception):
    pass


def http(method: str, url: str, body: dict | None = None, token: str | None = None,
         timeout: float = 10.0) -> tuple[int, dict | list | None]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as error:
        raise NetError(str(error)) from error


# ---------- fault control ----------

def toxi(method: str, path: str, body: dict | None = None) -> None:
    code, _ = http(method, TOXIPROXY + path, body)
    if code >= 300 and not (method == "DELETE" and code == 404):
        raise RuntimeError(f"toxiproxy {method} {path} → {code}")


def clear_faults() -> None:
    for hop in ("device_gateway", "gateway_agent", "agent_external"):
        toxi("POST", f"/proxies/{hop}", {"enabled": True})
        _, toxics = http("GET", f"{TOXIPROXY}/proxies/{hop}/toxics")
        for toxic in toxics or []:
            toxi("DELETE", f"/proxies/{hop}/toxics/{toxic['name']}")
    http("POST", f"{MOCKS}/admin/faults/clear")


def latency(hop: str, ms: int) -> None:
    toxi("POST", f"/proxies/{hop}/toxics",
         {"name": "lat", "type": "latency", "stream": "downstream", "toxicity": 1.0, "attributes": {"latency": ms}})


def arm(fault: str, tool: str) -> tuple[callable, threading.Timer | None]:
    """Injects `fault`; returns the callback that lifts it after the device's first attempt (and a timer, if any)."""
    lift = clear_faults
    timer = None
    if fault == "hop1_offline":
        toxi("POST", "/proxies/device_gateway", {"enabled": False})
        timer = threading.Timer(OFFLINE_S, lambda: toxi("POST", "/proxies/device_gateway", {"enabled": True}))
        timer.start()
        lift = lambda: None  # the network comes back on its own schedule
    elif fault == "hop1_lost_response":
        latency("device_gateway", int((CLIENT_TIMEOUT_S + 1) * 1000))   # gateway finishes, device times out
    elif fault == "hop2_lost_response":
        latency("gateway_agent", 3000)                                   # agent finishes, gateway (2 s) times out
    elif fault == "hop3_down":
        toxi("POST", "/proxies/agent_external", {"enabled": False})
    elif fault == "hop3_lost_response":
        path = "/hospital/bookings" if tool == "book_appointment" else "/notify"
        http("POST", f"{MOCKS}/admin/faults", {"path": path, "delay_s": 2, "count": 1})  # commits, agent (1 s) times out
    return lift, timer


# ---------- the device ----------

def fresh_key() -> str:
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def device_run(mode: str, token: str, step: dict, on_first: callable) -> dict:
    started = time.monotonic()
    persistent = step["stepKey"]
    keys: list[str] = []
    attempts = 0
    first = True

    def first_done() -> None:
        nonlocal first
        if first:
            first = False
            on_first()

    while time.monotonic() - started < BUDGET_S:
        key = fresh_key() if mode == "naive" else persistent
        keys.append(key)
        attempts += 1
        try:
            code, view = http("POST", f"{GATEWAY}/v1/actions", {**step, "stepKey": key}, token, CLIENT_TIMEOUT_S)
        except NetError:
            first_done()
            time.sleep(0.5)
            continue
        first_done()
        if code == 409:
            return result("CONFLICT", None, attempts, keys, started)
        if code != 200:
            time.sleep(0.5)
            continue
        status, reason = view["status"], view.get("reason")
        while status == "ACCEPTED" and time.monotonic() - started < BUDGET_S:
            time.sleep(POLL_S)
            try:
                code, view = http("GET", f"{GATEWAY}/v1/actions/{key}", None, token, CLIENT_TIMEOUT_S)
            except NetError:
                if mode == "naive":
                    break  # a naive client gives up on that request and submits a new one
                continue
            if code == 200:
                status, reason = view["status"], view.get("reason")
        if status in TERMINAL:
            return result(status, reason, attempts, keys, started)
    return result("TIMEOUT", None, attempts, keys, started)


def result(status: str, reason: str | None, attempts: int, keys: list[str], started: float) -> dict:
    return {"status": status, "reason": reason, "attempts": attempts, "distinct_keys": len(set(keys)),
            "duration_s": round(time.monotonic() - started, 3)}


# ---------- episodes ----------

def make_step(mode: str, tool: str, day: str, trace: str, preconditions: dict, expires_at_ms: int | None) -> dict:
    if tool == "book_appointment":
        payload = {"patient_id": "self", "department": "消化内科", "date": day, "note": "胃疼，想复诊", "trace": trace}
        identity = {k: payload[k] for k in ("patient_id", "department", "date")}
    else:
        payload = {"to": "女儿", "message": "我今天有点头晕", "trace": trace}
        identity = {"to": payload["to"]}
    step = {"stepKey": fresh_key(), "planId": uuid.uuid4().hex, "stepIndex": 0, "tool": tool,
            "toolClass": "IRREVERSIBLE", "identityArgs": identity, "payload": payload,
            "preconditions": {"toolVersion": "v1", **preconditions}, "createdAtMs": int(time.time() * 1000),
            "experimentMode": mode}
    if expires_at_ms is not None:
        step["expiresAtMs"] = expires_at_ms
    return step


def episode(mode: str, kind: str, scenario: str, tool: str, rep: int, day: str, token: str) -> dict:
    clear_faults()
    trace = uuid.uuid4().hex
    http("POST", f"{MOCKS}/admin/slots/{day}", {"available": 50})
    _, slot = http("GET", f"{MOCKS}/hospital/slots/{day}")
    preconditions: dict = {"slotVersion": slot["version"]} if tool == "book_appointment" else {}
    expires = None
    if scenario == "slot_taken":
        http("POST", f"{MOCKS}/admin/slots/{day}", {"available": 0})       # taken while the step was queued
    elif scenario == "still_valid":
        http("POST", f"{MOCKS}/admin/slots/{day}", {"available": 3})       # changed, but still bookable
    elif scenario == "tool_changed":
        preconditions["toolVersion"] = "v0"                                 # planned against an old contract
    elif scenario == "expired":
        expires = int(time.time() * 1000) - 3_600_000                       # "tell my daughter" an hour too late
    step = make_step(mode, tool, day, trace, preconditions, expires)

    lift, timer = arm(scenario, tool) if kind == "fault" else (lambda: None, None)
    try:
        outcome = device_run(mode, token, step, lift)
    finally:
        if timer:
            timer.join()
        clear_faults()
    time.sleep(0.3)  # let any held response finish before counting
    _, effects = http("GET", f"{MOCKS}/metrics/trace/{trace}")
    return {"mode": mode, "kind": kind, "scenario": scenario, "tool": tool, "rep": rep,
            "effects": effects["bookings"] + effects["notifications"], **outcome}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--condition", default="rephrase", choices=["rephrase", "identical"],
                        help="label only: must match the agent's MEDSYNC_EXPERIMENT_REPHRASE setting")
    parser.add_argument("--faults-only", action="store_true")
    args = parser.parse_args()

    code, session = http("POST", f"{GATEWAY}/v1/auth/register",
                         {"username": f"exp_{uuid.uuid4().hex[:10]}", "password": "experiment-pass-1"})
    if code != 201:
        print(f"cannot register through {GATEWAY} (HTTP {code}); is the experiment stack up?")
        return 1
    token = session["token"]

    plan = [("fault", f, t) for f in FAULTS for t in TOOLS]
    if not args.faults_only:
        plan += [("stale", s, t) for s, t in STALE.items()]
    rng = random.Random(args.seed)
    out = Path(__file__).parent / "results" / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.condition}.jsonl"
    total = args.reps * len(plan) * len(MODES)
    day0 = date(2027, 1, 1)
    n = 0
    with out.open("w") as sink:
        for rep in range(args.reps):
            for kind, scenario, tool in plan:
                modes = MODES[:]
                rng.shuffle(modes)  # no mode systematically runs first or last within a scenario
                for mode in modes:
                    day = (day0 + timedelta(days=n)).isoformat()
                    row = {"condition": args.condition, **episode(mode, kind, scenario, tool, rep, day, token)}
                    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                    sink.flush()
                    n += 1
                    print(f"[{n:>3}/{total}] {mode:10} {scenario:19} {tool:16} → {row['status']:10} "
                          f"effects={row['effects']} attempts={row['attempts']} {row['duration_s']}s", flush=True)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
