#!/usr/bin/env python3
"""Checks Langfuse tracing end to end: sends one two-step plan through the stack, reads its trace back.

    scripts/up.sh --langfuse && python3 scripts/langfuse_check.py

Expects: one trace for both steps, the graph nodes and MCP calls inside it, and no free text in it.
Keys come from .env and are not printed.
"""
import base64, json, sys, time, uuid, urllib.request
sys.path.insert(0, __import__("os").path.dirname(__file__))
import smoke

env = dict(l.rstrip("\n").split("=", 1) for l in open(".env") if "=" in l and not l.startswith("#"))
auth = base64.b64encode(f"{env['LANGFUSE_PUBLIC_KEY']}:{env['LANGFUSE_SECRET_KEY']}".encode()).decode()

def lf(path):
    req = urllib.request.Request("http://127.0.0.1:3000" + path, headers={"Authorization": "Basic " + auth})
    return json.load(urllib.request.urlopen(req, timeout=10))

status, session = smoke.http("POST", f"{smoke.GATEWAY}/v1/auth/register",
                             {"username": f"trace_{uuid.uuid4().hex[:8]}", "password": "trace-password-1"})
token = session["token"]
plan = uuid.uuid4().hex
secret = "今天头晕得厉害，别担心"
book = smoke.step("book_appointment", {"patient_id": "self", "department": "心内科", "date": "2026-12-03", "note": secret},
                  planId=plan, stepIndex=0)
notify = smoke.step("notify_family", {"to": "女儿", "message": secret}, planId=plan, stepIndex=1)
print("book", smoke.http("POST", f"{smoke.GATEWAY}/v1/actions", book, token)[1]["status"])
time.sleep(3)  # the second step arrives later, as after an offline queue
print("notify", smoke.http("POST", f"{smoke.GATEWAY}/v1/actions", notify, token)[1]["status"])

names, observations = set(), []
for _ in range(30):
    observations = lf(f"/api/public/v2/observations?sessionId={plan}&limit=100&fields=core,basic,io,metadata")["data"]
    names = {o["name"] for o in observations}
    if {"0:book_appointment", "1:notify_family"} <= names:
        break
    time.sleep(2)
print("observations for this plan:", len(observations))
print("distinct trace ids:", {o["traceId"] for o in observations})
print("names:", sorted(names))
dump = json.dumps(observations, ensure_ascii=False)
print("free text present:", secret in dump, "| redacted marker present:", f"<{len(secret)} chars>" in dump)
print("user ids:", {o.get("userId") for o in observations})
ok = (len({o["traceId"] for o in observations}) == 1 and {"0:book_appointment", "1:notify_family", "executor",
      "mcp:notify_family"} <= names and secret not in dump)
print("PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
