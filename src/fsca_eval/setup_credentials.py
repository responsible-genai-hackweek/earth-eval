"""One-time interactive Earthdata Login setup.

`earthaccess.login(strategy="interactive", persist=True)` prompts for a
username/password and writes them to `~/.netrc` itself -- outside this
repository. This script never reads, prints, logs, or persists credentials
anywhere under the repo; it only reports whether authentication succeeded.

Run once per machine before `cli.py run`/`resume`.
"""

from __future__ import annotations

import sys


def main() -> int:
    import earthaccess

    try:
        auth = earthaccess.login(strategy="interactive", persist=True)
    except Exception as exc:  # noqa: BLE001 - reported to the user, not swallowed
        print(f"Earthdata login failed: {exc}", file=sys.stderr)
        return 1

    if not getattr(auth, "authenticated", False):
        print("Earthdata login did not succeed.", file=sys.stderr)
        return 1

    print("Earthdata credentials verified and stored in ~/.netrc (not in this repository).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
