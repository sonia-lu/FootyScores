"""Step 1, FETCH: download the raw match data from olympics.com into data/raw/."""

import gzip
import json
import shutil
import sys
import time
import urllib.error
import urllib.request

from build import match_list
from config import (
    MAIN_GRID_FILE,
    MAIN_GRID_URL,
    MATCH_RAW_DIR,
    MATCH_URL,
    RAW_DIR,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    RETRIES,
    ROOT,
    START_LIST_FILE,
    START_LIST_URL,
)


def download(url: str) -> bytes:
    """Download one URL and return its body. Retries a few times on failure."""
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)

    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)

            # Fail (and retry) if the response is not valid JSON.
            json.loads(body)
            return body

        except (urllib.error.URLError, OSError, ValueError):
            is_last_attempt = attempt == RETRIES - 1
            if is_last_attempt:
                raise
            time.sleep(1 + attempt)  # wait 1s, then 2s, ... before trying again


def fetch() -> None:
    """Download the start list, the competition schedule and every match result into data/raw/."""
    start_list = download(START_LIST_URL)
    matches = match_list(json.loads(start_list))

    # Download everything into a temporary folder first ...
    temp_dir = RAW_DIR.with_name("raw.tmp")
    shutil.rmtree(temp_dir, ignore_errors=True)
    try:
        (temp_dir / MATCH_RAW_DIR.name).mkdir(parents=True)
        (temp_dir / START_LIST_FILE.name).write_bytes(start_list)
        (temp_dir / MAIN_GRID_FILE.name).write_bytes(download(MAIN_GRID_URL))

        match_number = 0
        for match in matches:
            match_number += 1
            match_id = match["code"]
            print(f"[{match_number}/{len(matches)}] {match_id}", file=sys.stderr)

            body = download(MATCH_URL.format(code=match_id))
            (temp_dir / MATCH_RAW_DIR.name / f"{match_id}.json").write_bytes(body)
    except BaseException:
        # A download failed (or Ctrl+C was pressed): remove the half-finished
        # temporary folder and keep data/raw/ as it was.
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    # ... and replace data/raw/ only after every download has succeeded.
    shutil.rmtree(RAW_DIR, ignore_errors=True)
    temp_dir.rename(RAW_DIR)
    print(f"Stored {len(matches)} matches in {RAW_DIR.relative_to(ROOT)}/", file=sys.stderr)
