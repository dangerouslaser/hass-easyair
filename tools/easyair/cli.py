"""Test CLI (run from the tools/ directory). Tokens are kept in ~/.easyair_tokens.json (chmod 600).

  python3 -m easyair.cli login            # prints a URL, then asks for the redirect URL
  python3 -m easyair.cli devices
  python3 -m easyair.cli details <gatewayId>
  python3 -m easyair.cli energy <gatewayId>
  python3 -m easyair.cli get </raw/path>
"""
import json
import os
import sys
from pathlib import Path

from .client import EasyAirClient, exchange_code, new_login

TOKEN_FILE = Path(os.environ.get("EASYAIR_TOKENS", Path.home() / ".easyair_tokens.json"))
PENDING_FILE = TOKEN_FILE.with_suffix(".pending.json")


def save(path: Path, data: dict):
    path.write_text(json.dumps(data))
    path.chmod(0o600)


def main(argv):
    cmd = argv[0] if argv else "help"
    if cmd == "login":
        req = new_login()
        save(PENDING_FILE, req)
        print("1. Open this URL in a browser and sign in with SingleKey ID:\n")
        print(req["url"])
        print("\n2. After sign-in the browser will try to open an idsmobileapp://?code=... link.")
        print("   Copy that full URL (Firefox: address bar; Chrome: DevTools > Network, the last")
        print("   'authorize'/'idpresponse' request's Location header), then run:")
        print("   python3 -m easyair.cli finish '<url>'")
    elif cmd == "finish":
        req = json.loads(PENDING_FILE.read_text())
        tokens = exchange_code(argv[1], req["verifier"])
        save(TOKEN_FILE, tokens)
        PENDING_FILE.unlink(missing_ok=True)
        print(f"Logged in. Tokens saved to {TOKEN_FILE}")
    else:
        tokens = json.loads(TOKEN_FILE.read_text())
        c = EasyAirClient(tokens, on_tokens=lambda t: save(TOKEN_FILE, t))
        if cmd == "devices":
            out = c.device_list()
        elif cmd == "details":
            out = c.device_details(argv[1])
        elif cmd == "energy":
            out = c.energy_usage(argv[1])
        elif cmd == "get":
            out = c.get(argv[1])
        else:
            print(__doc__)
            return
        print(json.dumps(out, indent=2) if not isinstance(out, str) else out)


if __name__ == "__main__":
    main(sys.argv[1:])
