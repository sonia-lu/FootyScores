"""Tests for FootyScores (fetch.py, convert.py, build.py, serve.py and the command line).

Run from the project folder with:

    python3 -m unittest discover -s tests -v

Every test builds into a temporary folder, so reference/ is never touched.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import build  # noqa: E402
import config  # noqa: E402
import convert  # noqa: E402
import fetch  # noqa: E402
import serve  # noqa: E402

EXAMPLE = json.loads((ROOT / "example.json").read_text(encoding="utf-8"))
OPTIONAL_GOAL_FIELDS = {"assist", "addedTime"}  # not every goal has these
POSITIONS = {"GK", "DF", "MF", "FW"}
GOAL_TYPES = {"open_play", "penalty", "free_kick", "own_goal", "other"}
USA_GUINEA = "FBLMTEAM11------------GPA-000600--"


class TempReference(unittest.TestCase):
    """Base class: each test builds into its own temporary reference/ folder."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.reference = self.temp / "reference"
        patcher = mock.patch.object(build, "REFERENCE_DIR", self.reference)
        patcher.start()
        self.addCleanup(patcher.stop)

    def use_corrections(self, corrections: dict):
        path = self.temp / "corrections.json"
        path.write_text(json.dumps(corrections), encoding="utf-8")
        patcher = mock.patch.object(build, "CORRECTIONS_FILE", path)
        patcher.start()
        self.addCleanup(patcher.stop)


class BuildTests(TempReference):
    """The real stored data builds into a complete and consistent reference."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as temp:
            with mock.patch.object(build, "REFERENCE_DIR", Path(temp)):
                cls.endpoints = build.build()
                cls.responses = {}
                for item in cls.endpoints:
                    cls.responses[item["id"]] = json.loads((Path(temp) / item["response"]).read_text(encoding="utf-8"))

    def test_one_endpoint_per_match(self):
        ids = [item["id"] for item in self.endpoints]
        self.assertEqual(len(ids), 58)
        self.assertEqual(len(set(ids)), 58)
        for item in self.endpoints:
            self.assertEqual(item["endpoint"], f"/match/{item['id']}")
            self.assertEqual(item["method"], "GET")

    def test_sorted_by_kickoff(self):
        kickoffs = [datetime.fromisoformat(item["kickoff"]) for item in self.endpoints]
        self.assertEqual(kickoffs, sorted(kickoffs))

    def test_matches_committed_reference(self):
        # The committed reference/ must be what the code produces from data/raw/.
        for item in self.endpoints:
            committed = json.loads((ROOT / "reference" / item["response"]).read_text(encoding="utf-8"))
            self.assertEqual(self.responses[item["id"]], committed, item["id"])

    def test_same_structure_as_example(self):
        for match_id, response in self.responses.items():
            with self.subTest(match_id):
                self.assertEqual(response.keys(), EXAMPLE.keys())
                for section in ("competition", "venue", "teams"):
                    self.assertEqual(response[section].keys(), EXAMPLE[section].keys())
                self.assertEqual(response["score"].keys(), EXAMPLE["score"].keys())
                self.assertIn(response["status"], {"FT", "AET", "PEN"})
                for side in ("home", "away"):
                    lineup = response["lineups"][side]
                    self.assertEqual(lineup.keys(), EXAMPLE["lineups"][side].keys())
                    self.assertEqual(len(lineup["startingXI"]), 11)
                    for player in lineup["startingXI"] + lineup["bench"]:
                        self.assertEqual(player.keys(), {"name", "number", "position"})
                        self.assertIn(player["position"], POSITIONS)

    def test_goals_are_complete_and_valid(self):
        for match_id, response in self.responses.items():
            with self.subTest(match_id):
                teams = response["teams"]
                home = [g for g in response["scorers"] if g["team"] == teams["home"]]
                away = [g for g in response["scorers"] if g["team"] == teams["away"]]
                self.assertEqual((len(home), len(away)), (response["score"]["home"], response["score"]["away"]))
                for goal in response["scorers"]:
                    self.assertTrue({"team", "player", "minute", "type"} <= goal.keys())
                    self.assertTrue(goal.keys() - {"team", "player", "minute", "type"} <= OPTIONAL_GOAL_FIELDS)
                    self.assertIn(goal["type"], GOAL_TYPES)
                    self.assertGreater(goal.get("addedTime", 1), 0)
                times = [convert.goal_time(g) for g in response["scorers"]]
                self.assertEqual(times, sorted(times))

    def test_stoppage_time_goal(self):
        # Putellas scored 17 minutes into stoppage time of a 90-minute match.
        response = self.responses["FBLWTEAM11------------GPC-000500--"]
        goal = [g for g in response["scorers"] if g["player"] == "Alexia Putellas"][0]
        self.assertEqual((goal["minute"], goal["addedTime"]), (90, 17))

    def test_correction_is_applied_and_noted(self):
        response = self.responses[USA_GUINEA]
        self.assertEqual([g["minute"] for g in response["scorers"]], [14, 31, 75])
        notes = [item["notes"] for item in self.endpoints if item["id"] == USA_GUINEA][0]
        self.assertEqual(len(notes), 1)
        self.assertIn("corrections.json", notes[0])


class ConsistencyTests(TempReference):
    """Data that contradicts itself must stop the build."""

    def test_extra_scorer_fails(self):
        self.use_corrections(
            {
                "FBLMTEAM11------------GPB-000100--": {
                    "source": "test",
                    "addScorers": [{"team": "Morocco", "player": "Nobody", "minute": 50, "type": "open_play"}],
                }
            }
        )
        with self.assertRaisesRegex(ValueError, "scorers add up to"):
            build.build()
        self.assertFalse(self.reference.exists(), "nothing may be written when the build fails")

    def test_missing_correction_fails(self):
        self.use_corrections({})  # the source only has the 75' goal of USA 3-0 Guinea
        with self.assertRaisesRegex(ValueError, "1-0 but the final score is 3-0"):
            build.build()

    def test_unknown_match_in_corrections_fails(self):
        self.use_corrections({"NO-SUCH-MATCH": {"source": "test", "addScorers": []}})
        with self.assertRaisesRegex(ValueError, "unknown match ids"):
            build.build()


class RebuildTests(TempReference):
    def test_unchanged_files_are_not_rewritten_and_stale_files_removed(self):
        build.build()
        endpoints_file = self.reference / "endpoints.json"
        stale_file = self.reference / "match" / "OLD.json"
        stale_file.write_text("{}", encoding="utf-8")
        modified = endpoints_file.stat().st_mtime_ns

        build.build()
        self.assertEqual(endpoints_file.stat().st_mtime_ns, modified)
        self.assertFalse(stale_file.exists())


class HelperTests(unittest.TestCase):
    def test_goal_minute(self):
        self.assertEqual(convert.goal_minute("23'"), (23, 0))
        self.assertEqual(convert.goal_minute("90' +3"), (90, 3))
        self.assertEqual(convert.goal_minute("120' +1"), (120, 1))

    def test_first_half_stoppage_sorts_before_second_half(self):
        goals = [{"minute": 46}, {"minute": 45, "addedTime": 2}, {"minute": 45}]
        self.assertEqual(sorted(goals, key=convert.goal_time), [goals[2], goals[1], goals[0]])

    def test_match_list_sorts_across_time_zones(self):
        def match(code, start):
            return {"code": code, "startDate": start, "start": [{}, {}]}

        # 15:00+02:00 is 13:00 UTC, so it kicks off before 14:30+01:00 (13:30 UTC).
        start_list = {
            "schedules": [
                match("B", "2024-07-24T14:30:00+01:00"),
                match("A", "2024-07-24T15:00:00+02:00"),
                {"code": "CEREMONY", "startDate": "2024-07-24T10:00:00+02:00", "start": []},
            ]
        }
        self.assertEqual([m["code"] for m in build.match_list(start_list)], ["A", "B"])

    def test_match_list_rejects_duplicates(self):
        schedule = {"code": "X", "startDate": "2024-07-24T15:00:00+02:00", "start": [{}, {}]}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build.match_list({"schedules": [schedule, schedule]})


class FetchTests(unittest.TestCase):
    def test_failed_fetch_keeps_old_data_and_leaves_no_temp_folder(self):
        temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp, ignore_errors=True)
        raw = temp / "raw"
        (raw / "RES_ByRSC_H2H").mkdir(parents=True)
        (raw / "SCH_StartList.json").write_text("old", encoding="utf-8")

        start_list = (ROOT / "data" / "raw" / "SCH_StartList.json").read_bytes()
        responses = [start_list, b"{}", OSError("network down")]

        def fake_download(url):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with mock.patch.multiple(
            fetch,
            RAW_DIR=raw,
            MATCH_RAW_DIR=raw / "RES_ByRSC_H2H",
            START_LIST_FILE=raw / "SCH_StartList.json",
            download=fake_download,
        ), mock.patch("sys.stderr"):
            with self.assertRaises(OSError):
                fetch.fetch()

        self.assertFalse((temp / "raw.tmp").exists())
        self.assertEqual((raw / "SCH_StartList.json").read_text(encoding="utf-8"), "old")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.endpoints = json.loads((ROOT / "reference" / "endpoints.json").read_text(encoding="utf-8"))
        cls.server = serve.make_server(cls.endpoints, "127.0.0.1", 0)  # port 0 = any free port
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, accept="application/json"):
        request = urllib.request.Request(self.base_url + path, headers={"Accept": accept})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.headers["Content-Type"], response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers["Content-Type"], error.read()

    def test_every_endpoint_returns_its_reference(self):
        for item in self.endpoints:
            with self.subTest(item["id"]):
                status, content_type, body = self.get(item["endpoint"])
                self.assertEqual(status, 200)
                self.assertEqual(content_type, config.JSON_CONTENT_TYPE)
                self.assertEqual(body, (ROOT / "reference" / item["response"]).read_bytes())

    def test_endpoint_list(self):
        status, _, body = self.get("/match")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), [item["endpoint"] for item in self.endpoints])

    def test_endpoint_list_in_browser(self):
        status, content_type, body = self.get("/match", accept="text/html")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, config.HTML_CONTENT_TYPE)
        self.assertEqual(body.count(b"<li>"), len(self.endpoints))

    def test_unknown_match_is_404(self):
        status, _, body = self.get("/match/NO-SUCH-MATCH")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))


class CommandLineTests(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "src" / "FootyScores.py"), *args], capture_output=True, text=True, timeout=30
        )

    def test_invalid_port_is_a_clear_error(self):
        result = self.run_script("--serve", "99999")
        self.assertEqual(result.returncode, 2)
        self.assertIn("PORT must be between 1 and 65535", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
