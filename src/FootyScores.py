# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""List the /match/<id> API endpoint of every Paris 2024 Olympic football match.

What this script does, step by step:

  1. FETCH  (only with --fetch)                                   -> fetch.py
     Download the raw match data from olympics.com into data/raw/.

  2. BUILD  (always)                                 -> build.py, convert.py
     Read the raw data from data/raw/ and write the expected API responses:
       reference/endpoints.json      - one entry per endpoint
       reference/match/<id>.json     - expected response of GET /match/<id>
     Then print every endpoint, one per line.

  3. SERVE  (only with --serve)                                   -> serve.py
     Start a small local API on http://127.0.0.1:<port> that answers each
     endpoint with its expected response, so tests can call it.

Settings such as paths and URLs are in config.py.

Endpoints are listed in kickoff order (date and time). If two matches kick off
at the same time, the match id decides the order.
"""

import argparse
import sys
import urllib.error
from pathlib import Path

from build import build
from config import DEFAULT_PORT, HOST, REFERENCE_DIR, ROOT
from fetch import fetch
from serve import serve


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List the /match/<id> API endpoint of every Paris 2024 Olympic football match.",
        epilog="Endpoints are sorted by kickoff date and time, then by match id.",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="download the source data into data/raw/ before building (otherwise no network is used)",
    )
    parser.add_argument(
        "--serve",
        nargs="?",
        type=int,
        const=DEFAULT_PORT,
        metavar="PORT",
        help=f"run a local API that answers the endpoints (default port {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        default=HOST,
        help=f"address the API listens on (default {HOST}, this computer only; 0.0.0.0 = all networks)",
    )
    parser.add_argument(
        "--extended",
        action="store_true",
        help='add "addedTime" to stoppage-time goals (not in example.json, so off by default)',
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REFERENCE_DIR,
        metavar="DIR",
        help=f"folder to write the responses to (default {REFERENCE_DIR.relative_to(ROOT)}/)",
    )
    args = parser.parse_args()

    if args.serve is not None and not 1 <= args.serve <= 65535:
        parser.error(f"PORT must be between 1 and 65535, not {args.serve}")

    try:
        if args.fetch:
            fetch()
        endpoints = build(args.out, args.extended)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
        sys.exit(f"Failed: {error}")

    if args.serve is not None:
        serve(endpoints, args.out, args.host, args.serve)
        return

    for item in endpoints:
        print(f"{item['method']} {item['endpoint']}")


# Run main() when the file is started with "python3 src/FootyScores.py".
if __name__ == "__main__":
    main()
