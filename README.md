# FootyScores

Builds a reference definition of the API endpoints for every Paris 2024
Olympic football match (58 in all), for use in automated API testing.

Each match gets one endpoint, `GET /match/<id>`, and an expected response in
exactly the structure of `example.json`. The id is the official Olympic match
code, e.g. `/match/FBLMTEAM11------------GPB-000100--` (Argentina v Morocco).

Requires Python 3.9+ and has no external dependencies.

## Usage

```sh
python3 FootyScores.py           # list all endpoints, using the stored data (no network)
python3 FootyScores.py --fetch   # download the data from olympics.com again first
```

Running the tool prints one endpoint per match, in kickoff order:

```
GET /match/FBLMTEAM11------------GPB-000100--
GET /match/FBLMTEAM11------------GPC-000100--
...
GET /match/FBLWTEAM11------------FNL-000100--
```

Each run also regenerates `reference/`, which holds the expected response for
every endpoint.

## Calling an endpoint

Start the local API (it keeps running until you press Ctrl+C):

```sh
python3 FootyScores.py --serve          # port 8000
python3 FootyScores.py --serve 9000     # another port
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

A known id returns `200` with the match in the `example.json` structure; an
unknown id returns `404` with `{"error": "..."}`. The server only listens on
this computer (127.0.0.1) and uses only the stored data. It also serves a small
football icon at `/favicon.ico`, so browsers show it in the tab instead of a 404.

The source data is already stored in `data/raw/`, so `--fetch` is only needed
to refresh it. A fetch only replaces the stored data once all 58 matches have
downloaded successfully.

## Files

```
FootyScores.py                    fetch, build and serve logic
config.py                         paths, URLs and other settings
data/raw/                         source data, stored exactly as downloaded
  SCH_StartList.json              list of all matches
  RES_ByRSC_H2H/<id>.json         full result for each match
data/corrections.json             hand-checked fixes for gaps in the source data
reference/                        generated, rebuilt from scratch on every run
  endpoints.json                  index of every endpoint (see below)
  match/<id>.json                 expected response for GET /match/<id>
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

`notes` lists known problems in the source data for that match, so a test can
skip or relax checks that would otherwise fail for reasons outside the API.

## Guarantees

- One endpoint per match: no duplicates (the build fails if a match id appears
  twice) and no omissions (the build fails if any match result is missing).
- Deterministic: the same stored data always produces byte-identical files.
- Order: endpoints are sorted by kickoff date and time, then by match id.
  Within a response, scorers are in the order the goals were scored, and
  players are in the order the source lists them (goalkeeper first).

## How response fields are filled

| Field | Source / rule |
| --- | --- |
| `competition.name` | `Paris 2024 Olympic Games - Men's Football` or `Women's Football` |
| `competition.round` | e.g. `Group B`, `Quarter-final`, `Gold Medal Match` |
| `status` | `FT`, `AET` (extra time) or `PEN` (penalty shoot-out) |
| `score` | Score after normal/extra time; shoot-out kicks are not included |
| `scorers.team` | Team credited with the goal (for own goals, the opponent) |
| `scorers.type` | `open_play`, `penalty`, `free_kick` or `own_goal` |
| `scorers.minute` | Minute as a number, including stoppage time (`90' +3` gives `93`) |
| `position` | `GK`, `DF`, `MF` or `FW`; the source has no finer positions |

## Corrections

`data/corrections.json` fills gaps in the downloaded data. It lives outside
`data/raw/`, so `--fetch` never overwrites it, and the build fails if it names
a match id that does not exist. Each entry gives a reason and a source, and
every corrected match says so in its `notes` in `reference/endpoints.json`.

Current correction: USA 3-0 Guinea (men's Group A,
`FBLMTEAM11------------GPA-000600--`). The olympics.com play-by-play only
records the 75' goal. The 14' (Mihailovic, free kick) and 31' (Paredes, assist
Aaronson) goals are added from the U.S. Soccer match report; the same
olympics.com file's player stats agree (Mihailovic 1 goal, Paredes 2,
Aaronson 1 assist, 2 goals in the first half).
