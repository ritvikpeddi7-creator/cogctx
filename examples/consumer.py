#!/usr/bin/env python3
"""
Example cogctx consumer: a polite notification daemon.

Asks the local cogctx server whether it may interrupt before surfacing a
non-urgent message. Absence of a server is never an error — per SPEC §5 the
consumer just behaves as it would without cogctx.

Run the reference server first:
    python3 ../reference/cogctx_server.py serve --simulate
"""

import json
import urllib.request

COGCTX_URL = "http://127.0.0.1:7710"


def may_interrupt() -> bool:
    try:
        with urllib.request.urlopen(f"{COGCTX_URL}/v1/should-interrupt", timeout=1) as r:
            answer = json.load(r)
        print(f"cogctx says: {answer['reason']}")
        return answer["interrupt_ok"]
    except OSError:
        return True  # no signal → behave normally (SPEC §5)


if __name__ == "__main__":
    if may_interrupt():
        print(">> showing notification: 'Your build finished.'")
    else:
        print(">> holding notification until the user leaves deep focus.")
