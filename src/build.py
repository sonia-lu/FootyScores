"""Step 2, BUILD: read data/raw/ and write the expected API responses to reference/.

    reference/endpoints.json      - one entry per endpoint
    reference/match/<id>.json     - expected response of GET /match/<id>
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import (
    CORRECTIONS_FILE,
    MATCH_RAW_DIR,
    ONE_LINE_LISTS,
    RAW_DIR,
    REFERENCE_DIR,
    ROOT,
    START_LIST_FILE,
)
from convert import convert


def match_list(start_list: dict) -> list:
    """Return all matches from the start list, sorted by kickoff time, then id."""
    matches = []
    for schedule in start_list["schedules"]:
        # The start list also contains medal ceremonies. They have no teams, so
        # only keep entries with at least two competitors.
        competitors = schedule.get("start", [])
        if len(competitors) >= 2:
            matches.append(schedule)

    # Stop if the same match id appears twice.
    seen_ids = set()
    duplicate_ids = set()
    for match in matches:
        if match["code"] in seen_ids:
            duplicate_ids.add(match["code"])
        seen_ids.add(match["code"])
    if duplicate_ids:
        raise ValueError(f"duplicate match ids in start list: {', '.join(sorted(duplicate_ids))}")

    # Compare kickoffs as real points in time, so that times with different
    # time zones (e.g. +02:00 and +01:00) are still in the right order.
    def kickoff_then_id(match: dict) -> tuple:
        return (datetime.fromisoformat(match["startDate"]), match["code"])

    return sorted(matches, key=kickoff_then_id)


def endpoint(match_id: str) -> str:
    """The API path of one match, e.g. /match/FBLMTEAM11------------GPB-000100--"""
    return f"/match/{match_id}"


def to_json(data, level: int = 0, key: Optional[str] = None) -> str:
    """Format data as JSON text, indented by 2 spaces per level.

    Same as json.dumps(data, indent=2), except that each player in a
    "startingXI" or "bench" list stays on a single line, as in example.json:

        "bench": [
          { "name": "Jane Doe", "number": 12, "position": "GK" },
          ...
        ]

    It calls itself for every nested object and list (level = nesting depth).
    """
    indent = "  " * level
    inner_indent = "  " * (level + 1)

    # A non-empty object: one "key": value line per field.
    if isinstance(data, dict) and data:
        lines = []
        for field_name, value in data.items():
            lines.append(f"{inner_indent}{json.dumps(field_name)}: {to_json(value, level + 1, field_name)}")
        return "{\n" + ",\n".join(lines) + f"\n{indent}}}"

    # A non-empty list: one line per item.
    if isinstance(data, list) and data:
        lines = []
        for item in data:
            if key in ONE_LINE_LISTS:
                # Write the whole player object on one line, as { ... }.
                fields = json.dumps(item, ensure_ascii=False)[1:-1]  # drop the outer { }
                lines.append(f"{inner_indent}{{ {fields} }}")
            else:
                lines.append(f"{inner_indent}{to_json(item, level + 1)}")
        return "[\n" + ",\n".join(lines) + f"\n{indent}]"

    # Anything else (text, number, true/false, null, {} or []).
    return json.dumps(data, ensure_ascii=False)


def update_reference(files: dict) -> None:
    """Make reference/ contain exactly these files: {<path>: <text>}.

    Files whose text is already correct are left untouched, and files that are
    no longer needed (e.g. a removed match) are deleted.
    """
    for path, text in files.items():
        if path.exists() and path.read_text(encoding="utf-8") == text:
            continue  # already up to date
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    if REFERENCE_DIR.exists():
        for path in REFERENCE_DIR.rglob("*"):
            if path.is_file() and path not in files:
                path.unlink()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> list:
    """Write reference/endpoints.json and one reference/match/<id>.json per match.

    Returns the list of endpoints (the content of endpoints.json).
    """
    if not START_LIST_FILE.exists():
        sys.exit(f"No stored data in {RAW_DIR.relative_to(ROOT)}/; run: python3 src/FootyScores.py --fetch")

    matches = match_list(read_json(START_LIST_FILE))
    match_ids = {match["code"] for match in matches}

    # Hand-checked fixes, keyed by match id. Stop if one names an unknown match.
    corrections = {}
    if CORRECTIONS_FILE.exists():
        corrections = read_json(CORRECTIONS_FILE)
    unknown_ids = sorted(set(corrections) - match_ids)
    if unknown_ids:
        raise ValueError(f"{CORRECTIONS_FILE.name} has unknown match ids: {', '.join(unknown_ids)}")

    endpoints = []
    responses = {}
    for match in matches:
        match_id = match["code"]
        raw_file = MATCH_RAW_DIR / f"{match_id}.json"
        if not raw_file.exists():
            sys.exit(f"Missing stored result for {match_id}; run: python3 src/FootyScores.py --fetch")

        notes = []
        response = convert(match, read_json(raw_file), corrections.get(match_id), notes)
        responses[match_id] = response
        endpoints.append(
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

    # Only write files once every match has converted without errors.
    files = {}
    for match_id, response in responses.items():
        files[REFERENCE_DIR / "match" / f"{match_id}.json"] = to_json(response) + "\n"
    files[REFERENCE_DIR / "endpoints.json"] = to_json(endpoints) + "\n"
    update_reference(files)

    return endpoints
