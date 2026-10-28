"""Settings and constants used by FootyScores.py."""

import base64
from pathlib import Path

# --- paths -------------------------------------------------------------------

# The project folder: one level above src/, where this file is.
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
START_LIST_FILE = RAW_DIR / "SCH_StartList.json"
MATCH_RAW_DIR = RAW_DIR / "RES_ByRSC_H2H"
# The olympics.com competition schedule (all sports). Not used to build the
# reference, only by the tests, to check the match list against it.
MAIN_GRID_FILE = RAW_DIR / "SCH_MainGridUnits.json"
# Hand-checked fixes for gaps in the downloaded data; kept outside data/raw/ so --fetch never overwrites them.
CORRECTIONS_FILE = ROOT / "data" / "corrections.json"
REFERENCE_DIR = ROOT / "reference"

# --- fetch -------------------------------------------------------------------

BASE_URL = "https://stacy.olympics.com/OG2024/data/"
START_LIST_URL = BASE_URL + "SCH_StartList~comp=OG2024~disc=FBL~lang=ENG.json"
MAIN_GRID_URL = BASE_URL + "SCH_MainGridUnits~comp=OG2024~lang=ENG.json"
MATCH_URL = BASE_URL + "RES_ByRSC_H2H~comp=OG2024~disc=FBL~rscResult={code}~lang=ENG.json"
REFERER = "https://stacy.olympics.com/en/paris-2024/schedule/football"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/26.6.2 Safari/605.1.15"
)
REQUEST_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": REFERER,
    "User-Agent": USER_AGENT,
}
REQUEST_TIMEOUT = 30  # seconds
RETRIES = 3

# --- build -------------------------------------------------------------------

GOAL_TYPES = {"SHOT": "open_play", "PEN": "penalty", "FRD": "free_kick", "OG": "own_goal"}
TOURNAMENTS = {"FBLMTEAM11": "Men's", "FBLWTEAM11": "Women's"}
ONE_LINE_LISTS = {"startingXI", "bench"}  # players stay on one line, as in example.json

# --- serve -------------------------------------------------------------------

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
JSON_CONTENT_TYPE = "application/json; charset=utf-8"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"

# 32x32 football icon served at /favicon.ico, so browsers do not log a 404.
FAVICON_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAr0lEQVR4nNXVUQ6AIAwDUA6x+19V/43b2lICLOFP6ENhjnFbRcRT"
    "jS2hSzHfRbuyIbJdsQAJUr1WFQAjZsItiK2A7lQ7ACmCDVErRRwBUBdT5k3t3nVGJIDjoMoA9B9wL8CBYOaXDcgNKBsSs5gCaDui"
    "YzfK8+1/wFVt+JEAd7UA9jrOAH7D2aakAspwFqA82wLQT6FcQSgcQaB9QA6vIEgntARnCGZYwlnMktCV9QJDf41sTWcYGwAAAABJ"
    "RU5ErkJggg=="
)
