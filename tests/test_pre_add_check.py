"""No-network unit tests for the pre-add "already released" classification
and SEASON_PROGRESSED detection (run: python -m tests.test_pre_add_check)."""

from app.domain.events import compare_states, pre_add_check

TODAY = "2026-09-15"

# --- pre_add_check: movies ---------------------------------------------
d = pre_add_check({"digital_release": "2001-12-01"}, "movie", TODAY)
assert d.code == "released" and d.date == "2001-12-01", f"{d}"

d = pre_add_check({"digital_release": "2030-05-01"}, "movie", TODAY)
assert d.code == "upcoming" and d.date == "2030-05-01", f"{d}"

# a date exactly today counts as released (date <= today)
d = pre_add_check({"digital_release": TODAY}, "movie", TODAY)
assert d.code == "released", f"{d}"

d = pre_add_check({}, "movie", TODAY)
assert d.code == "no_data", f"{d}"

# --- pre_add_check: TV/anime --------------------------------------------
tv_complete = {
    "latest_season": 2,
    "total_episodes_current_season": 7,
    "episodes_aired_current_season": 7,
}
d = pre_add_check(tv_complete, "tv", TODAY)
assert d.code == "season_complete" and d.season == 2, f"{d}"

# same check must work for the anime media type too
d = pre_add_check(tv_complete, "anime", TODAY)
assert d.code == "season_complete", f"{d}"

tv_airing = {
    "latest_season": 3,
    "total_episodes_current_season": 8,
    "episodes_aired_current_season": 4,
}
d = pre_add_check(tv_airing, "tv", TODAY)
assert d.code == "airing" and d.season == 3 and d.aired == 4 and d.total == 8, f"{d}"

# Announced-but-not-started season: TMDb keeps a single future-dated placeholder
# episode -> must classify as airing, NOT season_complete (live Silo S4 shape).
tv_announced_stub = {
    "latest_season": 4,
    "total_episodes_current_season": 1,
    "episodes_aired_current_season": 0,
}
d = pre_add_check(tv_announced_stub, "tv", TODAY)
assert d.code == "airing" and d.season == 4 and d.aired == 0 and d.total == 1, f"{d}"

# Mid-season: part aired, part still future (live Fonari S1 shape: 5 past + 3 future).
tv_midseason = {
    "latest_season": 1,
    "total_episodes_current_season": 8,
    "episodes_aired_current_season": 5,
}
d = pre_add_check(tv_midseason, "tv", TODAY)
assert d.code == "airing" and d.season == 1 and d.aired == 5 and d.total == 8, f"{d}"

d = pre_add_check({}, "tv", TODAY)
assert d.code == "no_data", f"{d}"


def _types(events):
    return [e.event_type for e in events]


# --- SEASON_PROGRESSED ----------------------------------------------------
old = {"latest_season": 2, "total_episodes_current_season": 7, "episodes_aired_current_season": 3}
new = {"latest_season": 2, "total_episodes_current_season": 7, "episodes_aired_current_season": 4}
evs = compare_states(old, new)
assert _types(evs) == ["SEASON_PROGRESSED"], f"{_types(evs)}"
assert evs[0].payload == {"season": 2}, f"{evs[0]}"

# nothing changed -> no events at all
old = {"latest_season": 2, "total_episodes_current_season": 7, "episodes_aired_current_season": 4}
new = dict(old)
assert compare_states(old, new) == [], "no-change must produce no events"

# season transition: only NEW_SEASON_ANNOUNCED (SEASON_PROGRESSED suppressed)
old = tv_complete
new = {"latest_season": 3, "total_episodes_current_season": 8, "episodes_aired_current_season": 1}
evs = compare_states(old, new)
assert _types(evs) == ["NEW_SEASON_ANNOUNCED"], f"{_types(evs)}"

# movie: digital date appears -> only DIGITAL_DATE_ANNOUNCED (no TV events)
evs = compare_states({}, {"digital_release": "2030-05-01"})
assert _types(evs) == ["DIGITAL_DATE_ANNOUNCED"], f"{_types(evs)}"

print("pre add check tests passed")
