# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""List the /match/<id> API endpoint of every Paris 2024 Olympic football match.

Each endpoint is printed on its own line, and its expected response is written
to reference/match/<id>.json.

By default the reference under reference/ is built only from the data stored
under data/raw/, without using the network. Pass --fetch to download that data
from olympics.com again first. Pass --serve to run a local API that answers
each endpoint with its expected response.

Endpoints are listed in kickoff order (date and time), with the match id as a
tie-break for matches that kick off at the same time.
"""

import argparse
import gzip
import html
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from config import (
    CORRECTIONS_FILE,
    DEFAULT_PORT,
    FAVICON_PNG,
    GOAL_TYPES,
    HOST,
    HTML_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    MATCH_RAW_DIR,
    MATCH_URL,
    ONE_LINE_LISTS,
    RAW_DIR,
    REFERENCE_DIR,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    RETRIES,
    ROOT,
    START_LIST_FILE,
    START_LIST_URL,
    TOURNAMENTS,
)


# --- fetch -------------------------------------------------------------------


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            json.loads(body)  # only store responses that are valid JSON
            return body
        except (urllib.error.URLError, OSError, ValueError):
            if attempt == RETRIES - 1:
                raise
            time.sleep(1 + attempt)


def fetch() -> None:
    """Download the start list and every match result, stored exactly as received."""
    start_list = download(START_LIST_URL)
    matches = match_list(json.loads(start_list))

    staging = RAW_DIR.with_name("raw.tmp")
    shutil.rmtree(staging, ignore_errors=True)
    (staging / MATCH_RAW_DIR.name).mkdir(parents=True)
    (staging / START_LIST_FILE.name).write_bytes(start_list)
    for i, match in enumerate(matches, 1):
        print(f"[{i}/{len(matches)}] {match['code']}", file=sys.stderr)
        body = download(MATCH_URL.format(code=match["code"]))
        (staging / MATCH_RAW_DIR.name / f"{match['code']}.json").write_bytes(body)

    # Replace the stored data only once every download has succeeded.
    shutil.rmtree(RAW_DIR, ignore_errors=True)
    staging.rename(RAW_DIR)
    print(f"Stored {len(matches)} matches in {RAW_DIR.relative_to(ROOT)}/", file=sys.stderr)


# --- build -------------------------------------------------------------------


def match_list(start_list: dict) -> list:
    # Victory ceremonies are listed too, but have no teams.
    matches = [s for s in start_list["schedules"] if len(s.get("start", [])) >= 2]
    codes = [m["code"] for m in matches]
    duplicates = sorted({c for c in codes if codes.count(c) > 1})
    if duplicates:
        raise ValueError(f"duplicate match ids in start list: {', '.join(duplicates)}")
    return sorted(matches, key=lambda m: (m["startDate"], m["code"]))


def endpoint(match_id: str) -> str:
    return f"/match/{match_id}"


def person_name(person: dict) -> str:
    name = f"{person.get('givenName', '')} {person.get('familyName', '')}".strip()
    return name or person.get("TVName") or person["name"]


def entry_value(entries: list, code: str, pos: Optional[str] = None) -> Optional[str]:
    """Value of the first source "eventUnitEntries" item with this code."""
    for e in entries:
        if e["eue_code"] == code and (pos is None or e.get("eue_pos") == pos):
            return e["eue_value"]
    return None


def lineup(item: dict) -> dict:
    coaches = {c["function"]["functionCode"]: c["coach"] for c in item.get("teamCoaches", [])}
    coach = coaches.get("COACH") or coaches.get("SI_COA")
    players = sorted(item.get("teamAthletes", []), key=lambda a: (a["order"], int(a["bib"])))

    def player(athlete: dict) -> dict:
        return {
            "name": person_name(athlete["athlete"]),
            "number": int(athlete["bib"]),
            "position": entry_value(athlete.get("eventUnitEntries", []), "POSITION", "1"),
        }

    starters, bench = [], []
    for athlete in players:
        is_starter = entry_value(athlete.get("eventUnitEntries", []), "STARTER") == "Y"
        (starters if is_starter else bench).append(athlete)
    return {
        "team": item["participant"]["shortName"],
        "formation": entry_value(item["eventUnitEntries"], "FORMATION"),
        "coach": person_name(coach) if coach else None,
        "startingXI": [player(a) for a in starters],
        "bench": [player(a) for a in bench],
    }


def scorers(results: dict, sides: dict, names: dict) -> list:
    actions = sorted(
        (
            a
            for period in results["playByPlay"]
            if period["subcode"] != "PSO"  # shoot-out kicks are not goals
            for a in period["actions"]
            if a.get("pbpa_Result") == "GOAL" and "pbpa_ScoreH" in a
        ),
        key=lambda a: a["pbpa_order"],
    )
    goals = []
    home = 0
    for action in actions:
        # The running score shows who was credited, which also covers own goals.
        new_home = int(action["pbpa_ScoreH"])
        side = "home" if new_home > home else "away"
        home = new_home

        athletes = {a.get("pbpat_role"): a["pbpat_code"] for a in action["competitors"][0]["athletes"]}
        scorer = athletes.get("SCR") or next(iter(athletes.values()))
        # "90' +3" means 3 minutes of stoppage time after the 90th minute, so minute 93.
        minute, _, added = action["pbpa_When"].partition("+")
        goal = {
            "team": sides[side],
            "player": names.get(scorer),
            "minute": int(re.match(r"\d+", minute).group()) + int(added or 0),
        }
        if "ASSIST" in athletes:
            goal["assist"] = names.get(athletes["ASSIST"])
        goal["type"] = GOAL_TYPES.get(action["pbpa_Action"], "other")
        goals.append(goal)
    return goals


def convert(match: dict, data: dict, correction: Optional[dict], notes: list) -> dict:
    """Turn one stored match result into the structure of example.json."""
    results = data["results"]
    items = {entry_value(i["eventUnitEntries"], "HOME_AWAY").lower(): i for i in results["items"]}
    sides = {side: item["participant"]["shortName"] for side, item in items.items()}
    names = {
        a["participantCode"]: person_name(a["athlete"])
        for item in results["items"]
        for a in item.get("teamAthletes", [])
    }
    periods = {p["p_code"]: p for p in results["periods"]}
    total, half = periods["TOT"], periods["H1"]

    status = "FT"
    if "PSO" in periods:
        status = "PEN"
    elif "ET-H2" in periods:
        status = "AET"

    goals = scorers(results, sides, names)
    if correction:
        added = correction["addScorers"]
        goals = sorted(goals + added, key=lambda g: g["minute"])
        minutes = ", ".join(f"{g['minute']}'" for g in added)
        notes.append(f"scorers at {minutes} added from {CORRECTIONS_FILE.name} (source: {correction['source']})")
    score = {"home": int(total["home"]["score"]), "away": int(total["away"]["score"])}
    credited = (
        sum(1 for g in goals if g["team"] == sides["home"]),
        sum(1 for g in goals if g["team"] == sides["away"]),
    )
    if credited != (score["home"], score["away"]):
        notes.append(
            f"play-by-play has {credited[0]}-{credited[1]} in goals but the final score is "
            f"{score['home']}-{score['away']}; the source data is missing scorers"
        )

    location = results["schedule"]["location"]["longDescription"]
    return {
        "competition": {
            "name": f"Paris 2024 Olympic Games - {TOURNAMENTS[match['code'][:10]]} Football",
            "season": "2024",
            "round": results["eventUnit"]["shortDescription"],
        },
        "venue": {
            "name": results["schedule"]["venue"]["description"],
            "city": location.rsplit(", ", 1)[-1],
        },
        "kickoff": match["startDate"],
        "status": status,
        "teams": {"home": sides["home"], "away": sides["away"]},
        "score": {
            **score,
            "halfTime": {"home": int(half["home"]["score"]), "away": int(half["away"]["score"])},
        },
        "scorers": goals,
        "lineups": {"home": lineup(items["home"]), "away": lineup(items["away"])},
    }


def to_json(data, level: int = 0, key: Optional[str] = None) -> str:
    """Indent like json.dumps(indent=2), but put each player on a single line."""
    pad, inner = "  " * level, "  " * (level + 1)
    if isinstance(data, dict) and data:
        fields = [f"{inner}{json.dumps(k)}: {to_json(v, level + 1, k)}" for k, v in data.items()]
        return "{\n" + ",\n".join(fields) + f"\n{pad}}}"
    if isinstance(data, list) and data:
        if key in ONE_LINE_LISTS:
            items = [f"{inner}{{ {json.dumps(p, ensure_ascii=False)[1:-1]} }}" for p in data]
        else:
            items = [f"{inner}{to_json(v, level + 1)}" for v in data]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(data, ensure_ascii=False)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(data) + "\n", encoding="utf-8")


def build() -> list:
    """Write reference/endpoints.json and one reference/match/<id>.json per match."""
    if not START_LIST_FILE.exists():
        sys.exit(f"No stored data in {RAW_DIR.relative_to(ROOT)}/; run: python3 FootyScores.py --fetch")

    matches = match_list(json.loads(START_LIST_FILE.read_text(encoding="utf-8")))
    corrections = {}
    if CORRECTIONS_FILE.exists():
        corrections = json.loads(CORRECTIONS_FILE.read_text(encoding="utf-8"))
    unknown = sorted(set(corrections) - {m["code"] for m in matches})
    if unknown:
        raise ValueError(f"{CORRECTIONS_FILE.name} has unknown match ids: {', '.join(unknown)}")
    index = []
    responses = {}
    for match in matches:
        match_id = match["code"]
        raw_file = MATCH_RAW_DIR / f"{match_id}.json"
        if not raw_file.exists():
            sys.exit(f"Missing stored result for {match_id}; run: python3 FootyScores.py --fetch")
        notes = []
        data = json.loads(raw_file.read_text(encoding="utf-8"))
        response = convert(match, data, corrections.get(match_id), notes)
        responses[match_id] = response
        index.append(
            {
                "id": match_id,
                "endpoint": endpoint(match_id),
                "method": "GET",
                "kickoff": response["kickoff"],
                "teams": response["teams"],
                "response": f"match/{match_id}.json",
                "notes": notes,
            }
        )

    # Rebuild from scratch so removed matches never leave stale files behind.
    shutil.rmtree(REFERENCE_DIR, ignore_errors=True)
    for match_id, response in responses.items():
        write_json(REFERENCE_DIR / "match" / f"{match_id}.json", response)
    write_json(REFERENCE_DIR / "endpoints.json", index)
    return index


# --- serve -------------------------------------------------------------------


def endpoint_links(index: list) -> bytes:
    """HTML page that lists every endpoint as a link, for browsing /match."""
    rows = "\n".join(
        f'<li><a href="{html.escape(item["endpoint"])}">{html.escape(item["endpoint"])}</a> '
        f'{html.escape(item["kickoff"])} &middot; '
        f'{html.escape(item["teams"]["home"])} v {html.escape(item["teams"]["away"])}</li>'
        for item in index
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Match endpoints</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.6; }}
  a {{ font-family: ui-monospace, monospace; margin-right: 0.5rem; }}
</style>
</head>
<body>
<h1>Match endpoints ({len(index)})</h1>
<ol>
{rows}
</ol>
</body>
</html>
"""
    return page.encode()


def serve(index: list, port: int) -> None:
    """Answer GET /match/<id> with that match's reference response."""
    responses = {item["endpoint"]: REFERENCE_DIR / item["response"] for item in index}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path).rstrip("/")
            if path == "/match" and "text/html" in self.headers.get("Accept", ""):
                self.reply(200, endpoint_links(index), HTML_CONTENT_TYPE)  # browsers get clickable links
            elif path == "/match":
                body = json.dumps([item["endpoint"] for item in index], indent=2).encode()
                self.reply(200, body)
            elif path in responses:
                self.reply(200, responses[path].read_bytes())
            elif path == "/favicon.ico":
                self.reply(200, FAVICON_PNG, "image/png")
            else:
                self.reply(404, json.dumps({"error": f"no match at {path}"}).encode())

        def reply(self, status: int, body: bytes, content_type: str = JSON_CONTENT_TYPE) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((HOST, port), Handler)
    base_url = f"http://{HOST}:{port}"
    for item in index:
        print(f"{item['method']} {base_url}{item['endpoint']}")
    print(f"\nServing {len(index)} endpoints on {base_url} (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


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
    args = parser.parse_args()

    try:
        if args.fetch:
            fetch()
        index = build()
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        sys.exit(f"Failed: {exc}")

    if args.serve is not None:
        serve(index, args.serve)
        return

    for item in index:
        print(f"{item['method']} {item['endpoint']}")


if __name__ == "__main__":
    main()
