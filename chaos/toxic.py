#!/usr/bin/env python3
"""Fault injection on the three hops via the Toxiproxy control API (stdlib only).

    python3 chaos/toxic.py list
    python3 chaos/toxic.py lost-response agent_external   # side effect commits, response arrives after the caller gave up
    python3 chaos/toxic.py reset gateway_agent            # connections reset by peer
    python3 chaos/toxic.py latency device_gateway 3000    # slow network
    python3 chaos/toxic.py down agent_external            # hop unreachable (offline)
    python3 chaos/toxic.py up agent_external
    python3 chaos/toxic.py clear                          # remove every toxic on every hop

Hops: device_gateway (①), gateway_agent (②), agent_external (③).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

API = os.environ.get("TOXIPROXY_URL", "http://127.0.0.1:8474")
HOPS = ("device_gateway", "gateway_agent", "agent_external")


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def add(hop: str, name: str, kind: str, stream: str, attributes: dict) -> None:
    call("POST", f"/proxies/{hop}/toxics",
         {"name": name, "type": kind, "stream": stream, "toxicity": 1.0, "attributes": attributes})
    print(f"{hop}: +{name} ({kind}, {stream}) {attributes}")


def clear(hop: str) -> None:
    for toxic in call("GET", f"/proxies/{hop}/toxics") or []:
        call("DELETE", f"/proxies/{hop}/toxics/{toxic['name']}")
    call("POST", f"/proxies/{hop}", {"enabled": True})


def main(argv: list[str]) -> None:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return
    command, args = argv[0], argv[1:]
    if command == "list":
        for name, proxy in sorted(call("GET", "/proxies").items()):
            toxics = ", ".join(f"{t['name']}({t['type']})" for t in proxy["toxics"]) or "-"
            print(f"{name:15} {'up' if proxy['enabled'] else 'DOWN':4} {proxy['listen']:>16} -> "
                  f"{proxy['upstream']:12} toxics: {toxics}")
    elif command == "clear":
        for hop in args or HOPS:
            clear(hop)
        print("cleared")
    elif command in {"down", "up"}:
        call("POST", f"/proxies/{args[0]}", {"enabled": command == "up"})
        print(f"{args[0]}: {command}")
    elif command == "lost-response":
        # The request reaches upstream and commits; the response is delayed past the caller's read timeout.
        add(args[0], "lost_response", "latency", "downstream", {"latency": int(args[1]) if len(args) > 1 else 30000})
    elif command == "reset":
        add(args[0], "reset", "reset_peer", "upstream", {"timeout": int(args[1]) if len(args) > 1 else 0})
    elif command == "latency":
        add(args[0], "latency", "latency", "downstream", {"latency": int(args[1]), "jitter": int(args[1]) // 5})
    else:
        sys.exit(f"unknown command: {command}\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
