# FootyScores

Builds a reference definition of the API endpoints for every Paris 2024
Olympic football match (58 in all), for use in automated API testing.

Each match gets one endpoint, `GET /match/<id>`, and an expected response in
the structure of `example.json`. The id is the official Olympic match code,
e.g. `/match/FBLMTEAM11------------GPB-000100--` (Argentina v Morocco).

## Install

Requires Python 3.9 or newer. There are no other dependencies, so nothing
needs to be installed with `pip`.

```sh
git clone https://github.com/sonia-lu/FootyScores.git
cd FootyScores
python3 --version          # must print 3.9 or newer
```

The source data is already stored in `data/raw/`, so the tool works offline
straight after cloning.

## Usage

```sh
python3 src/FootyScores.py           # list all endpoints, using the stored data (no network)
python3 src/FootyScores.py --fetch   # download the data from olympics.com again first
```

Running the tool prints one endpoint per match, in kickoff order:

```
GET /match/FBLMTEAM11------------GPB-000100--
GET /match/FBLMTEAM11------------GPC-000100--
...
GET /match/FBLWTEAM11------------FNL-000100--
```

Each run also brings `reference/` up to date. It holds the expected response
for every endpoint. Only files whose content changed are rewritten.

A fetch only replaces the stored data once all 58 matches have downloaded
successfully. If a download fails, `data/raw/` stays as it was and no
temporary files are left behind.

## Calling an endpoint

Start the local API (it keeps running until you press Ctrl+C):

```sh
python3 src/FootyScores.py --serve          # port 8000
python3 src/FootyScores.py --serve 9000     # another port
```

It first prints every endpoint as a full URL, then waits for requests:

```
GET http://127.0.0.1:8000/match/FBLMTEAM11------------GPB-000100--
...
GET http://127.0.0.1:8000/match/FBLWTEAM11------------FNL-000100--

Serving 58 endpoints on http://127.0.0.1:8000 (Ctrl+C to stop)
```

Then, in another terminal (or a browser, Postman, or a test suite):

```sh
curl http://127.0.0.1:8000/match/FBLMTEAM11------------GPB-000100--
curl http://127.0.0.1:8000/match        # list of all endpoints
```

Opening http://127.0.0.1:8000/match in a browser shows every endpoint as a
link, with its kickoff and teams; tools like `curl` get the list as JSON.

| Request | Response |
| --- | --- |
| `GET /match/<known id>` | `200`, the match in the `example.json` structure |
| `GET /match/<unknown id>` | `404`, `{"error": "..."}` |
| `GET /match` | `200`, list of all endpoints |
| `GET /favicon.ico` | `200`, a small football icon for the browser tab |

By default the API only accepts connections from this computer (127.0.0.1).
Use `--host 0.0.0.0` to accept them from other machines too (see
[Deploy](#deploy)).

## Tests

```sh
python3 -m unittest discover -s tests -v
```

The tests use only Python's built-in `unittest` and build into a temporary
folder, so they never change `reference/`. They check that:

- there is exactly one endpoint per match, sorted by kickoff;
- every response has the `example.json` structure, and its scorers add up to
  the final score;
- the committed `reference/` matches what the code produces from `data/raw/`
  (so a code change that alters a response must also update `reference/`);
- inconsistent data or corrections stop the build;
- a failed `--fetch` keeps the old data;
- the API answers every endpoint with its reference file, and unknown ids with `404`.

GitHub Actions runs the tests on every push and pull request, on Python 3.9
and 3.12 (`.github/workflows/tests.yml`).

## Deploy

The API is a single Python process that serves files from `reference/`, so it
can run on any server with Python 3.9+:

```sh
git clone https://github.com/sonia-lu/FootyScores.git
cd FootyScores
python3 src/FootyScores.py --serve 8000 --host 0.0.0.0
```

Use a process manager (e.g. systemd) to keep it running. The API is read-only
and has no authentication, so only expose it on a network that your tests
use, not on the public internet.

## Files

```
src/                              all the code
  FootyScores.py                  command line: runs the steps below
  fetch.py                        step 1: download the data from olympics.com
  build.py                        step 2: build reference/ from data/raw/
  convert.py                      turn one raw match into an example.json response
  serve.py                        step 3: the local API
  config.py                       paths, URLs and other settings
data/raw/                         source data, stored exactly as downloaded
  SCH_StartList.json              list of all matches
  RES_ByRSC_H2H/<id>.json         full result for each match
data/corrections.json             hand-checked fixes for gaps in the source data
reference/                        generated, kept up to date on every run
  endpoints.json                  index of every endpoint (see below)
  match/<id>.json                 expected response for GET /match/<id>
tests/                            automated tests
```

Each entry in `reference/endpoints.json`:

```json
{
  "id": "FBLMTEAM11------------GPB-000100--",
  "endpoint": "/match/FBLMTEAM11------------GPB-000100--",
  "method": "GET",
  "kickoff": "2024-07-24T15:00:00+02:00",
  "teams": { "home": "Argentina", "away": "Morocco" },
  "response": "match/FBLMTEAM11------------GPB-000100--.json",
  "notes": []
}
```

`notes` lists hand-made corrections for that match (see
[Corrections](#corrections)), so a test can tell which values did not come
from the source data.

## Why the endpoints look like this

The brief does not fix the endpoint format, so the id in `/match/<id>` is the
official olympics.com match code, e.g. `FBLMTEAM11------------GPB-000100--`:

- **Unique and stable.** It is the key olympics.com itself uses, so it never
  changes between runs or fetches, and every response can be traced back to
  its source file `data/raw/RES_ByRSC_H2H/<id>.json`.
- **Readable.** It says which match it is: `FBLMTEAM11` / `FBLWTEAM11` = men's
  / women's tournament, then the round (`GPB` = Group B, `QFNL` =
  quarter-final, `SFNL` = semi-final, `FNL` = final) and the match number.
- **Alternatives considered.** A sequential number (`/match/1`) would change
  meaning if the order or data ever changed. Team names
  (`/match/argentina-morocco`) are not unique once the same teams can meet
  again in a later round.

The dashes are part of the code and need no URL escaping.

## Guarantees

- One endpoint per match: no duplicates (the build fails if a match id appears
  twice) and no omissions (the build fails if any match result is missing).
- Consistent: in every response, the scorers add up to the final score. If
  they do not (in the source data or after a correction), the build fails and
  names the match, rather than producing a reference that contradicts itself.
- Deterministic: the same stored data always produces byte-identical files.
- Order: endpoints are sorted by kickoff time (compared as real points in
  time, so different time zones sort correctly), then by match id. Within a
  response, scorers are in the order the goals were scored, and players are in
  the order the source lists them (goalkeeper first).

## How response fields are filled

| Field | Source / rule |
| --- | --- |
| `competition.name` | `Paris 2024 Olympic Games - Men's Football` or `Women's Football` |
| `competition.round` | e.g. `Group B`, `Quarter-final`, `Gold Medal Match` |
| `status` | `FT`, `AET` (extra time) or `PEN` (penalty shoot-out) |
| `score` | Score after normal/extra time; shoot-out kicks are not included |
| `scorers.team` | Team credited with the goal (for own goals, the opponent) |
| `scorers.type` | `open_play`, `penalty`, `free_kick` or `own_goal` |
| `scorers.minute` | Minute of the goal as a number, e.g. `23` |
| `scorers.addedTime` | Only for stoppage-time goals: `90' +3` gives `"minute": 90, "addedTime": 3` |
| `position` | `GK`, `DF`, `MF` or `FW` (see below) |

**Differences from `example.json`:**

- **`addedTime`** is an extra field that `example.json` does not have. Without
  it, a goal at `90' +17` would have to be either `107`, which looks like an
  extra-time goal, or `90`, which loses information. It only appears on
  stoppage-time goals, so other goals have exactly the `example.json` fields.
- **`position`** uses the four broad positions (`GK`, `DF`, `MF`, `FW`), not
  specific ones like `RB`, `CB` or `ST` as in `example.json`. This is a
  choice, not a limit of the data: the source also gives every starter a
  formation slot code (e.g. `D05`, `M27`) from which specific positions could
  be derived. That mapping depends on each formation and was not done, so that
  every position in the reference comes directly from the source.

## Corrections

`data/corrections.json` fills gaps in the downloaded data. It lives outside
`data/raw/`, so `--fetch` never overwrites it. The build fails if it names a
match id that does not exist, or if a match's scorers then do not add up to
its final score. Each entry gives a reason and a source, and every corrected
match says so in its `notes` in `reference/endpoints.json`.

Current correction: USA 3-0 Guinea (men's Group A,
`FBLMTEAM11------------GPA-000600--`). The olympics.com play-by-play only
records the 75' goal. The 14' (Mihailovic, free kick) and 31' (Paredes, assist
Aaronson) goals are added from the U.S. Soccer match report; the same
olympics.com file's player stats agree (Mihailovic 1 goal, Paredes 2,
Aaronson 1 assist, 2 goals in the first half).
