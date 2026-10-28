"""Turn one raw olympics.com match result into a response like example.json.

Field names in the raw olympics.com data are short codes. The ones used here:

  "eventUnitEntries"   a list of { "eue_code": <name>, "eue_value": <value> }
                       items, e.g. { "eue_code": "FORMATION", "eue_value": "4-4-2" }
  periods "p_code"     H1 = first half, TOT = full match, ET-H2 = second half
                       of extra time, PSO = penalty shoot-out
  "pbpa_..."           one play-by-play action (a goal, a card, ...):
                         pbpa_Result  "GOAL" for goals
                         pbpa_ScoreH  home team's score after this action
                         pbpa_When    time of the action, e.g. "90' +3"
                         pbpa_Action  kind of goal, e.g. "PEN" (see GOAL_TYPES)
                         pbpa_order   position of the action in the match
  "pbpat_role"         a player's role in an action: SCR = scorer, ASSIST = assist
"""

import re
from typing import Optional

from config import CORRECTIONS_FILE, GOAL_TYPES, TOURNAMENTS


def person_name(person: dict) -> str:
    """Full name of a player or coach, e.g. "Julian Alvarez"."""
    given_name = person.get("givenName", "")
    family_name = person.get("familyName", "")
    name = f"{given_name} {family_name}".strip()

    # Fall back to other name fields if the first and last name are missing.
    if name:
        return name
    if person.get("TVName"):
        return person["TVName"]
    return person["name"]


def entry_value(entries: list, code: str, pos: Optional[str] = None) -> Optional[str]:
    """Look up a value in an "eventUnitEntries" list by its code.

    Example: entry_value(entries, "FORMATION") returns "4-4-2".
    If pos is given, the entry must also have that "eue_pos".
    Returns None if there is no such entry.
    """
    for entry in entries:
        if entry["eue_code"] != code:
            continue
        if pos is not None and entry.get("eue_pos") != pos:
            continue
        return entry["eue_value"]
    return None


def lineup(team: dict) -> dict:
    """Build the "lineups.home" or "lineups.away" part of a response."""
    # Find the head coach (code "COACH", or "SI_COA" in some matches).
    coaches_by_role = {}
    for team_coach in team.get("teamCoaches", []):
        role = team_coach["function"]["functionCode"]
        coaches_by_role[role] = team_coach["coach"]
    coach = coaches_by_role.get("COACH") or coaches_by_role.get("SI_COA")

    # Keep players in the order the source lists them (goalkeeper first);
    # players with the same order are sorted by shirt number.
    def source_order(athlete: dict) -> tuple:
        return (athlete["order"], int(athlete["bib"]))

    players = sorted(team.get("teamAthletes", []), key=source_order)

    def player_json(athlete: dict) -> dict:
        entries = athlete.get("eventUnitEntries", [])
        return {
            "name": person_name(athlete["athlete"]),
            "number": int(athlete["bib"]),  # "bib" = shirt number
            "position": entry_value(entries, "POSITION", "1"),
        }

    starting_xi = []
    bench = []
    for athlete in players:
        entries = athlete.get("eventUnitEntries", [])
        if entry_value(entries, "STARTER") == "Y":
            starting_xi.append(player_json(athlete))
        else:
            bench.append(player_json(athlete))

    return {
        "team": team["participant"]["shortName"],
        "formation": entry_value(team["eventUnitEntries"], "FORMATION"),
        "coach": person_name(coach) if coach else None,
        "startingXI": starting_xi,
        "bench": bench,
    }


def goal_minute(when: str) -> tuple:
    """Split a match time into (minute, added time).

    "23'"    -> (23, 0)
    "90' +3" -> (90, 3)   (3 minutes into stoppage time after the 90th minute)
    """
    minute_part, _, added_part = when.partition("+")
    minute = int(re.match(r"\d+", minute_part).group())
    added = int(added_part) if added_part else 0
    return (minute, added)


def goal_time(goal: dict) -> tuple:
    """Sort key that puts goals in the order they were scored (45+2 before 46)."""
    return (goal["minute"], goal.get("addedTime", 0))


def scorers(results: dict, team_names: dict, player_names: dict) -> list:
    """Build the "scorers" list of a response, in the order the goals were scored.

    team_names:   {"home": <team name>, "away": <team name>}
    player_names: {<player id>: <player name>}
    """
    # Collect every goal from the play-by-play.
    goal_actions = []
    for period in results["playByPlay"]:
        if period["subcode"] == "PSO":
            continue  # penalty shoot-out kicks do not count as goals
        for action in period["actions"]:
            if action.get("pbpa_Result") == "GOAL" and "pbpa_ScoreH" in action:
                goal_actions.append(action)

    def match_order(action: dict):
        return action["pbpa_order"]

    goal_actions.sort(key=match_order)

    goals = []
    home_score = 0
    for action in goal_actions:
        # Which team got the goal? If the home score went up it was the home
        # team, otherwise the away team. This also handles own goals correctly.
        new_home_score = int(action["pbpa_ScoreH"])
        if new_home_score > home_score:
            side = "home"
        else:
            side = "away"
        home_score = new_home_score

        # Player ids by role, e.g. {"SCR": <scorer id>, "ASSIST": <assist id>}.
        players_by_role = {}
        for athlete in action["competitors"][0]["athletes"]:
            players_by_role[athlete.get("pbpat_role")] = athlete["pbpat_code"]

        # Use the scorer if one is marked, otherwise the first player listed.
        scorer_id = players_by_role.get("SCR")
        if not scorer_id:
            scorer_id = list(players_by_role.values())[0]

        minute, added_time = goal_minute(action["pbpa_When"])
        goal = {
            "team": team_names[side],
            "player": player_names.get(scorer_id),
            "minute": minute,
        }
        if added_time:
            goal["addedTime"] = added_time
        if "ASSIST" in players_by_role:
            goal["assist"] = player_names.get(players_by_role["ASSIST"])
        goal["type"] = GOAL_TYPES.get(action["pbpa_Action"], "other")
        goals.append(goal)

    return goals


def count_goals(goals: list, team_name: str) -> int:
    """How many of these goals were credited to this team."""
    count = 0
    for goal in goals:
        if goal["team"] == team_name:
            count += 1
    return count


def convert(match: dict, data: dict, correction: Optional[dict], notes: list, extended: bool = False) -> dict:
    """Turn one raw match result into a response with the structure of example.json.

    correction: hand-checked fixes from data/corrections.json, or None.
    notes:      known problems with this match's data are added to this list.
    extended:   also give stoppage-time goals an "addedTime" field, which
                example.json does not have (90' +3 -> minute 90, addedTime 3).
    """
    results = data["results"]

    # The two teams, keyed by "home" and "away".
    teams = {}
    for team in results["items"]:
        side = entry_value(team["eventUnitEntries"], "HOME_AWAY").lower()
        teams[side] = team

    team_names = {}
    for side, team in teams.items():
        team_names[side] = team["participant"]["shortName"]

    # Every player's name, keyed by player id.
    player_names = {}
    for team in results["items"]:
        for athlete in team.get("teamAthletes", []):
            player_names[athlete["participantCode"]] = person_name(athlete["athlete"])

    # Scores per period: "TOT" = full match, "H1" = first half.
    periods = {}
    for period in results["periods"]:
        periods[period["p_code"]] = period
    full_time = periods["TOT"]
    half_time = periods["H1"]

    if "PSO" in periods:
        status = "PEN"  # decided by penalty shoot-out
    elif "ET-H2" in periods:
        status = "AET"  # decided after extra time
    else:
        status = "FT"  # full time

    goals = scorers(results, team_names, player_names)

    # Add scorers that are missing from the source data.
    if correction:
        added_goals = correction["addScorers"]
        goals = sorted(goals + added_goals, key=goal_time)

        minutes = ", ".join(f"{goal['minute']}'" for goal in added_goals)
        notes.append(f"scorers at {minutes} added from {CORRECTIONS_FILE.name} (source: {correction['source']})")

    home_score = int(full_time["home"]["score"])
    away_score = int(full_time["away"]["score"])

    # Stop if the scorers do not add up to the final score: the reference must
    # never contradict itself. Fix it in data/corrections.json.
    home_goals = count_goals(goals, team_names["home"])
    away_goals = count_goals(goals, team_names["away"])
    if home_goals != home_score or away_goals != away_score:
        raise ValueError(
            f"{match['code']} ({team_names['home']} v {team_names['away']}): the scorers add up to "
            f"{home_goals}-{away_goals} but the final score is {home_score}-{away_score}; "
            f"check the source data and {CORRECTIONS_FILE.name}"
        )

    # By default keep exactly the fields of example.json, so 90' +3 is just minute 90.
    if not extended:
        for goal in goals:
            if "addedTime" in goal:
                del goal["addedTime"]

    tournament = TOURNAMENTS[match["code"][:10]]  # first 10 characters: men's or women's
    location = results["schedule"]["location"]["longDescription"]  # e.g. "Parc des Princes, Paris"
    city = location.rsplit(", ", 1)[-1]  # the text after the last ", "

    return {
        "competition": {
            "name": f"Paris 2024 Olympic Games - {tournament} Football",
            "season": "2024",
            "round": results["eventUnit"]["shortDescription"],
        },
        "venue": {
            "name": results["schedule"]["venue"]["description"],
            "city": city,
        },
        "kickoff": match["startDate"],
        "status": status,
        "teams": {"home": team_names["home"], "away": team_names["away"]},
        "score": {
            "home": home_score,
            "away": away_score,
            "halfTime": {
                "home": int(half_time["home"]["score"]),
                "away": int(half_time["away"]["score"]),
            },
        },
        "scorers": goals,
        "lineups": {"home": lineup(teams["home"]), "away": lineup(teams["away"])},
    }
