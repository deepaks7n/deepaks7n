import datetime as dt
import io
import json
import urllib.error

import pytest

from scripts import update_stats
from scripts.update_stats import (
    STATS_END,
    STATS_START,
    ContributionDay,
    fetch_calendar,
    render_heatmap,
    replace_stats_block,
    summarise,
)

START = dt.date(2026, 10, 4)  # a Sunday


def week_of(counts: list[int], start: dt.date = START) -> list[ContributionDay]:
    return [
        ContributionDay(start + dt.timedelta(days=i), count, min(count, 4))
        for i, count in enumerate(counts)
    ]


def test_heatmap_has_a_cell_per_day_and_labels_non_zero_counts():
    svg = render_heatmap([week_of([0, 3, 0, 120, 0, 0, 1])])
    assert svg.count("<title>") == 7
    assert ">3</text>" in svg and ">120</text>" in svg and ">1</text>" in svg
    assert ">0</text>" not in svg


def test_heatmap_puts_sunday_on_the_top_row():
    svg = render_heatmap([week_of([5, 0, 0, 0, 0, 0, 0])])
    assert f'y="{update_stats.TOP}" width' in svg.split("<title>5 on")[0]


def test_summary_reports_total_busiest_and_streaks():
    weeks = [week_of([1, 2, 0, 4, 5, 6, 0])]
    line = summarise(weeks, today=START + dt.timedelta(days=6))
    assert "**18** contributions" in line
    assert "busiest day **6** (09 Oct 2026)" in line
    assert "current streak **3** days" in line
    assert "longest streak **3** days" in line


def test_summary_resets_current_streak_after_a_missed_day():
    weeks = [week_of([1, 1, 0, 0, 0, 0, 0])]
    assert "current streak **0** days" in summarise(weeks, today=START + dt.timedelta(days=6))


def test_summary_ignores_future_days_and_handles_empty_calendar():
    assert "No contributions" in summarise([week_of([9] * 7)], today=START - dt.timedelta(days=1))
    assert "No contributions" in summarise([], today=START)


def test_replace_stats_block_swaps_only_the_marked_text():
    readme = f"top\n{STATS_START}\nold\n{STATS_END}\nbottom"
    assert replace_stats_block(readme, "new") == f"top\n{STATS_START}\nnew\n{STATS_END}\nbottom"


def test_replace_stats_block_without_markers_fails_with_a_fix():
    with pytest.raises(ValueError, match="Add both markers"):
        replace_stats_block("no markers here", "new")


def fake_response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode())


def test_fetch_calendar_parses_weeks(monkeypatch):
    day = {"date": "2026-10-04", "contributionCount": 7, "contributionLevel": "THIRD_QUARTILE"}
    payload = {
        "data": {
            "user": {
                "contributionsCollection": {
                    "contributionCalendar": {"weeks": [{"contributionDays": [day]}]}
                }
            }
        }
    }
    monkeypatch.setattr(
        update_stats.urllib.request, "urlopen", lambda *a, **k: fake_response(payload)
    )
    assert fetch_calendar("someone", "token") == [[ContributionDay(START, 7, 3)]]


def test_fetch_calendar_reports_unknown_user(monkeypatch):
    payload = {"data": {"user": None}, "errors": [{"message": "Could not resolve"}]}
    monkeypatch.setattr(
        update_stats.urllib.request, "urlopen", lambda *a, **k: fake_response(payload)
    )
    with pytest.raises(RuntimeError, match="Check PROFILE_USERNAME"):
        fetch_calendar("nobody", "token")


def test_fetch_calendar_reports_network_failure(monkeypatch):
    def fail(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(update_stats.urllib.request, "urlopen", fail)
    with pytest.raises(RuntimeError, match="GH_TOKEN is valid"):
        fetch_calendar("someone", "token")


def test_main_requires_token_and_username(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("PROFILE_USERNAME", raising=False)
    with pytest.raises(SystemExit, match="Set GH_TOKEN"):
        update_stats.main()


def test_summary_counts_todays_contributions():
    line = summarise([week_of([0, 0, 0, 0, 0, 0, 2])], today=START + dt.timedelta(days=6))
    assert "**2** contributions" in line and "current streak **1** day" in line
