#!/usr/bin/env python3
"""End-to-end check of the three-hop exactly-once path against the running Compose stack (stdlib only).

    docker compose up --build -d && python3 scripts/smoke.py

Talks to the gateway the way a device does (through Toxiproxy hop ①) and reads ground truth straight from the
mocks' /metrics/side_effects, never from what the gateway or agent report.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

GATEWAY = os.environ.get("MEDSYNC_GATEWAY", "http://127.0.0.1:18081")
MOCKS = os.environ.get("MEDSYNC_MOCKS", "http://127.0.0.1:9100")
TOXIC = [sys.executable, os.path.join(os.path.dirname(__file__), "..", "chaos", "toxic.py")]


def http(method: str, url: str, body: dict | None = None, token: str | None = None, timeout: float = 30):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, None


def toxic(*args: str) -> None:
    subprocess.run([*TOXIC, *args], check=True, stdout=subprocess.DEVNULL)


def step(tool: str, payload: dict, **extra) -> dict:
    key = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    return {"stepKey": key, "planId": uuid.uuid4().hex, "stepIndex": 0, "tool": tool, "toolClass": "IRREVERSIBLE",
            "identityArgs": {k: payload[k] for k in ("department", "date") if k in payload}, "payload": payload,
            "preconditions": {"toolVersion": "v1"}, "createdAtMs": int(time.time() * 1000), **extra}


def bookings_for(ref: str) -> int:
    return len(http("GET", f"{MOCKS}/hospital/bookings?ref={ref}")[1])


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


def main() -> int:
    toxic("clear")
    http("POST", f"{MOCKS}/admin/reset")
    status, session = http("POST", f"{GATEWAY}/v1/auth/register",
                           {"username": f"smoke_{uuid.uuid4().hex[:8]}", "password": "smoke-password-1"})
    if status != 201:
        print(f"cannot register through {GATEWAY} (HTTP {status}); is the stack up?")
        return 1
    token = session["token"]
    book = {"patient_id": "p1", "department": "cardiology", "date": "2026-11-18", "note": ""}
    results = []

    print("1. happy path + replay")
    s1 = step("book_appointment", book)
    _, v = http("POST", f"{GATEWAY}/v1/actions", s1, token)
    _, again = http("POST", f"{GATEWAY}/v1/actions", s1, token)
    results.append(check("booked once, replay returns the same result",
                         v["status"] == again["status"] == "DONE" and bookings_for(s1["stepKey"]) == 1, v["status"]))
    code, _ = http("POST", f"{GATEWAY}/v1/actions", {**s1, "payload": {**book, "date": "2026-11-19"}}, token)
    results.append(check("same step_key with different content is rejected", code == 409, f"HTTP {code}"))

    print("2. hop ③ response lost after the hospital committed")
    # The booking commits, then the reply is held 8 s (> the agent's 5 s timeout): the classic ambiguous timeout.
    http("POST", f"{MOCKS}/admin/faults", {"path": "/hospital/bookings", "delay_s": 8, "count": 1})
    s2 = step("book_appointment", book)
    _, v = http("POST", f"{GATEWAY}/v1/actions", s2, token)
    committed = bookings_for(s2["stepKey"])
    time.sleep(4)  # let the held reply finish so the next attempt is a clean reconcile, not a busy lease
    _, polled = http("GET", f"{GATEWAY}/v1/actions/{s2['stepKey']}", token=token)
    results.append(check("first answer is ACCEPTED, poll reconciles to DONE, still one booking",
                         v["status"] == "ACCEPTED" and polled["status"] == "DONE" and committed == 1
                         and bookings_for(s2["stepKey"]) == 1,
                         f"{v['status']} → {polled['status']}, bookings={bookings_for(s2['stepKey'])}"))

    print("3. hop ② gateway→agent down, then back")
    toxic("down", "gateway_agent")
    s3 = step("notify_family", {"to": "daughter", "message": "I feel dizzy"})
    _, v = http("POST", f"{GATEWAY}/v1/actions", s3, token)
    toxic("up", "gateway_agent")
    _, polled = http("GET", f"{GATEWAY}/v1/actions/{s3['stepKey']}", token=token)
    _, polled2 = http("GET", f"{GATEWAY}/v1/actions/{s3['stepKey']}", token=token)
    sent = len(http("GET", f"{MOCKS}/notify?ref={s3['stepKey']}")[1])
    results.append(check("queued while hop ② is down, sent exactly once after",
                         v["status"] == "ACCEPTED" and polled["status"] == polled2["status"] == "DONE" and sent == 1,
                         f"{v['status']} → {polled['status']}, notifications={sent}"))

    print("4. slot taken while the step waited offline")
    http("POST", f"{MOCKS}/admin/slots/2026-11-21", {"available": 0})
    s4 = step("book_appointment", {**book, "date": "2026-11-21"})
    _, v = http("POST", f"{GATEWAY}/v1/actions", s4, token)
    options = (v.get("result") or {}).get("options", [])
    choice = next((o for o in options if o.get("decision") == "choose"), None)
    ok = v["status"] == "NEEDS_USER" and v["reason"] == "slot_full" and choice is not None
    if ok:
        _, done = http("POST", f"{GATEWAY}/v1/actions/{s4['stepKey']}/resume",
                       {"decision": "choose", "date": choice["date"]}, token)
        ok = done["status"] == "DONE" and bookings_for(s4["stepKey"]) == 1
    results.append(check("asks the user, books the chosen alternative once", ok, v.get("reason") or v["status"]))

    print("5. safety review of medication records (gateway → agent → RAG → gateway's delegated list)")
    now = int(time.time() * 1000)

    def record(name: str, minutes_ago: int = 0) -> dict:
        s = step("record_medication", {"name": name, "takenAt": now - minutes_ago * 60_000, "note": ""},
                 toolClass="WRITE_IDEMPOTENT")
        return http("POST", f"{GATEWAY}/v1/actions", s, token, timeout=60)[1]

    first = record("华法林", minutes_ago=60)
    results.append(check("first record has nothing to compare with", first["status"] == "DONE"
                         and not first["result"]["safety"]["alerts"], json.dumps(first["result"]["safety"].get("status"))))
    second = record("布洛芬")
    safety = (second.get("result") or {}).get("safety") or {}
    alert = next((a for a in safety.get("alerts", []) if a["with"] == "华法林"), None)
    excerpt = alert["findings"][0]["citation"]["excerpt"] if alert else ""
    results.append(check("ibuprofen after warfarin raises a cited alert", second["status"] == "DONE"
                         and second["reason"] == "safety_alert_moderate" and "anticoagulant" in excerpt,
                         second.get("reason") or second["status"]))
    record("泰诺", minutes_ago=30)
    dup = record("FLONASE Headache and Allergy Relief")
    results.append(check("same ingredient twice in a day is graded high", dup.get("reason") == "safety_alert_high",
                         dup.get("reason") or dup["status"]))

    print("6. cross-agent conflict: a message queued offline vs the safety review that came after")
    plan = uuid.uuid4().hex
    rec = step("record_medication", {"name": "对乙酰氨基酚", "takenAt": now, "note": ""}, toolClass="WRITE_IDEMPOTENT",
               planId=plan)
    msg = step("notify_family", {"to": "女儿", "message": "吃了对乙酰氨基酚，告诉女儿我没事"}, planId=plan, stepIndex=1)
    http("POST", f"{GATEWAY}/v1/actions", rec, token, timeout=60)  # 泰诺 was recorded above: duplicate → high
    _, paused = http("POST", f"{GATEWAY}/v1/actions", msg, token, timeout=60)
    sent_while_paused = len(http("GET", f"{MOCKS}/notify?ref={msg['stepKey']}")[1])
    ok = paused["status"] == "NEEDS_USER" and paused["reason"] == "conflict_with_later_finding" \
        and paused["result"]["conflicts"] and sent_while_paused == 0
    results.append(check("high alert pauses the queued message, nothing sent", ok, paused.get("reason") or ""))
    _, done = http("POST", f"{GATEWAY}/v1/actions/{msg['stepKey']}/resume", {"decision": "send_with_note"}, token)
    sent = http("GET", f"{MOCKS}/notify?ref={msg['stepKey']}")[1]
    results.append(check("send_with_note sends once, warning appended", done["status"] == "DONE" and len(sent) == 1
                         and "MedSync 用药提醒" in sent[0]["message"], done["status"]))
    plan = uuid.uuid4().hex
    rec = step("record_medication", {"name": "Aleve", "takenAt": now, "note": ""}, toolClass="WRITE_IDEMPOTENT",
               planId=plan)
    msg = step("notify_family", {"to": "女儿", "message": "吃了Aleve，告诉女儿我在家"}, planId=plan, stepIndex=1)
    reviewed = http("POST", f"{GATEWAY}/v1/actions", rec, token, timeout=60)[1]
    _, neutral = http("POST", f"{GATEWAY}/v1/actions", msg, token, timeout=60)
    results.append(check("moderate alert + neutral message is not paused", reviewed.get("reason") ==
                         "safety_alert_moderate" and neutral["status"] == "DONE", neutral["status"]))

    metrics =http("GET", f"{MOCKS}/metrics/side_effects")[1]
    dupes = sum(len(v) for v in metrics["duplicated"].values())
    results.append(check("no duplicated side effects overall", dupes == 0, json.dumps(metrics["duplicated"])))
    print(f"\n{sum(results)}/{len(results)} checks passed · side effects: {metrics['bookings']} bookings, "
          f"{metrics['notifications']} notifications")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
