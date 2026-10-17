"""Render the profile contribution heatmap and stats line from the GitHub GraphQL API.

Usage: GH_TOKEN=... PROFILE_USERNAME=deepaks7n python scripts/update_stats.py
"""

import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

GRAPHQL_URL = "https://api.github.com/graphql"
ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
HEATMAP = ROOT / "assets" / "stats" / "contribution-heatmap.svg"
STATS_START = "<!-- PROFILE-STATS:START -->"
STATS_END = "<!-- PROFILE-STATS:END -->"

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}
"""

LEVELS = ("NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE")
CELL = 15
GAP = 3
LEFT = 34
TOP = 22


@dataclass(frozen=True)
class ContributionDay:
    """One day on the contribution calendar."""

    date: dt.date
    count: int
    level: int


Week = list[ContributionDay]


def fetch_calendar(username: str, token: str) -> list[Week]:
    """Fetch the last year of contribution days for a user, grouped by week."""
    body = json.dumps({"query": QUERY, "variables": {"login": username}}).encode()
    request = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Fetching contributions for {username!r} failed: {error}. "
            "Check network access and that GH_TOKEN is valid."
        ) from error
    if payload.get("errors") or not (payload.get("data") or {}).get("user"):
        raise RuntimeError(
            f"GitHub GraphQL returned no calendar for {username!r}: {payload.get('errors')}. "
            "Check PROFILE_USERNAME."
        )
    weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [
        [
            ContributionDay(
                date=dt.date.fromisoformat(day["date"]),
                count=day["contributionCount"],
                level=LEVELS.index(day["contributionLevel"]),
            )
            for day in week["contributionDays"]
        ]
        for week in weeks
    ]


def _cell(x: int, y: int, day: ContributionDay) -> str:
    title = f"<title>{day.count} on {day.date.isoformat()}</title>"
    rect = f'<rect class="l{day.level}" x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2">'
    label = ""
    if day.count:
        size = 7 if day.count < 100 else 5
        label = (
            f'<text class="n{day.level}" x="{x + CELL / 2}" y="{y + CELL / 2 + 2.5}" '
            f'font-size="{size}">{day.count}</text>'
        )
    return f"{rect}{title}</rect>{label}"


def _month_labels(weeks: list[Week]) -> list[str]:
    labels = []
    last_month = None
    for index, week in enumerate(weeks):
        month = week[0].date.month
        if month != last_month and week[0].date.day <= 7:
            x = LEFT + index * (CELL + GAP)
            labels.append(f'<text class="axis" x="{x}" y="14">{week[0].date:%b}</text>')
        last_month = month
    return labels


def render_heatmap(weeks: list[Week]) -> str:
    """Render the calendar as a theme-aware SVG with the count printed in each cell."""
    width = LEFT + len(weeks) * (CELL + GAP) + 8
    height = TOP + 7 * (CELL + GAP) + 26
    parts = _month_labels(weeks)
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        y = TOP + row * (CELL + GAP) + CELL - 4
        parts.append(f'<text class="axis" x="4" y="{y}">{name}</text>')
    for index, week in enumerate(weeks):
        x = LEFT + index * (CELL + GAP)
        for day in week:
            y = TOP + ((day.date.weekday() + 1) % 7) * (CELL + GAP)
            parts.append(_cell(x, y, day))
    legend_y = height - 18
    parts.append(f'<text class="axis" x="{LEFT}" y="{legend_y + 10}">Less</text>')
    for level in range(5):
        x = LEFT + 30 + level * (CELL + GAP)
        parts.append(
            f'<rect class="l{level}" x="{x}" y="{legend_y}" width="12" height="12" rx="2"/>'
        )
    parts.append(f'<text class="axis" x="{LEFT + 124}" y="{legend_y + 10}">More</text>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace">'
        f"<style>{_STYLE}</style>"
        f'<rect class="bg" width="{width}" height="{height}" rx="6"/>'
        f"{''.join(parts)}</svg>\n"
    )


_STYLE = (
    ".bg{fill:#ffffff}.axis{fill:#57606a;font-size:9px}"
    "text[class^=n]{text-anchor:middle;font-weight:600}"
    ".l0{fill:#ebedf0}.l1{fill:#9be9a8}.l2{fill:#40c463}.l3{fill:#30a14e}.l4{fill:#216e39}"
    ".n1,.n2{fill:#0a3d1a}.n3,.n4{fill:#ffffff}"
    "@media (prefers-color-scheme:dark){"
    ".bg{fill:#0d1117}.axis{fill:#8b949e}"
    ".l0{fill:#161b22}.l1{fill:#0e4429}.l2{fill:#006d32}.l3{fill:#26a641}.l4{fill:#39d353}"
    ".n1,.n2{fill:#d1f5d9}.n3,.n4{fill:#04260f}}"
)


def summarise(weeks: list[Week], today: dt.date) -> str:
    """Summarise the year as one Markdown line: total, busiest day, and streaks."""
    days = [day for week in weeks for day in week if day.date <= today]
    if not days:
        return "_No contributions in the last year yet._"
    total = sum(day.count for day in days)
    busiest = max(days, key=lambda day: day.count)
    longest = run = 0
    for day in days:
        run = run + 1 if day.count else 0
        longest = max(longest, run)
    current = 0
    trailing = days[:-1] if days[-1].count == 0 else days
    for day in reversed(trailing):
        if not day.count:
            break
        current += 1
    return (
        f"**{total:,}** contributions in the last year · "
        f"busiest day **{busiest.count}** ({busiest.date:%d %b %Y}) · "
        f"current streak {_days(current)} · longest streak {_days(longest)}"
    )


def _days(count: int) -> str:
    return f"**{count}** day" if count == 1 else f"**{count}** days"


def replace_stats_block(readme: str, block: str) -> str:
    """Replace the text between the PROFILE-STATS markers in the README."""
    pattern = re.compile(f"{re.escape(STATS_START)}.*?{re.escape(STATS_END)}", re.DOTALL)
    if not pattern.search(readme):
        raise ValueError(
            f"README has no {STATS_START} ... {STATS_END} block. "
            "Add both markers where the stats line should go."
        )
    return pattern.sub(lambda _: f"{STATS_START}\n{block}\n{STATS_END}", readme)


def main() -> None:
    """Fetch the calendar, then write the heatmap SVG and the README stats line."""
    token = os.environ.get("GH_TOKEN")
    username = os.environ.get("PROFILE_USERNAME")
    if not token or not username:
        raise SystemExit("Set GH_TOKEN and PROFILE_USERNAME before running update_stats.py.")
    weeks = fetch_calendar(username, token)
    HEATMAP.parent.mkdir(parents=True, exist_ok=True)
    HEATMAP.write_text(render_heatmap(weeks))
    stats = summarise(weeks, dt.datetime.now(dt.UTC).date())
    README.write_text(replace_stats_block(README.read_text(), stats))


if __name__ == "__main__":
    main()
