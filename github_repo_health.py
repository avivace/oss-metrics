#!/usr/bin/env python3
"""

Notes:
  - "created in the last day"   = created within the last 24h, in ANY state
                                  (still open, closed, or merged)
  - "accepted in the past day"  = merged within the last 24h
  - "rejected in the past day"  = closed unmerged within the last 24h
  - ages are computed over the currently-open PRs/issues

Usage:
    ./github_repo_health.py [owner/repo]     # default: DataDog/datadog-agent

Token: GITHUB_TOKEN or GH_TOKEN env var, else falls back to `gh auth token`.
Dependencies: none (stdlib only).
"""

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REPO = sys.argv[1] if len(sys.argv) > 1 else "DataDog/datadog-agent"
API = "https://api.github.com"
WINDOW = timedelta(days=1)


def get_token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except Exception:
        return None


TOKEN = get_token()
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "repo-health-script",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"
else:
    print("warning: no GitHub token found (unauthenticated rate limits apply)",
          file=sys.stderr)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def gh_api(path: str, params: dict | None = None) -> dict | list:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def paginate(path: str, params: dict | None = None, label: str = "") -> list:
    """Walk every page of a list endpoint, logging progress."""
    items, page = [], 1
    base = dict(params or {}, per_page=100)
    while True:
        if label:
            log(f"  {label}: fetching page {page}...")
        batch = gh_api(path, {**base, "page": page})
        if not batch:
            return items
        items.extend(batch)
        if len(batch) < 100:
            return items
        page += 1


def gh_search(query: str, label: str = "") -> int:
    if label:
        log(f"  {label}...")
    data = gh_api("/search/issues", {"q": query, "per_page": 1})
    return data.get("total_count", 0)


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def ages_stats(items: list, now: datetime) -> tuple[int, float, float]:
    """Return (count, avg_age_seconds, max_age_seconds)."""
    ages = [(now - parse_ts(it["created_at"])).total_seconds() for it in items]
    if not ages:
        return 0, 0.0, 0.0
    return len(ages), sum(ages) / len(ages), max(ages)


def fmt_days(seconds: float) -> str:
    """Format an age adaptively (seconds/minutes/hours when recent, days when
    older), always with the equivalent decimal number of days appended."""
    seconds = max(0.0, seconds)
    days = seconds / 86400
    if seconds < 60:
        human = f"{seconds:.0f}s"
    elif seconds < 3600:
        human = f"{seconds // 60:.0f}m {seconds % 60:.0f}s"
    elif seconds < 86400:
        human = f"{seconds // 3600:.0f}h {(seconds % 3600) // 60:.0f}m"
    else:
        human = f"{seconds // 86400:.0f}d {(seconds % 86400) // 3600:.0f}h"
    return f"{human} ({days:.3f} days)"


def main() -> None:
    now = datetime.now(timezone.utc)
    cutoff = (now - WINDOW).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"repo:    {REPO}")
    print(f"now:     {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"window:  last 24h (since {cutoff})")
    print("-" * 60)

    # --- Open PRs (REST /pulls returns PRs only) ---
    log("[1/4] Fetching open PRs...")
    open_prs = paginate(f"/repos/{REPO}/pulls", {"state": "open"}, label="open PRs")
    log(f"  -> {len(open_prs)} open PRs")
    n_prs, avg_pr_age, max_pr_age = ages_stats(open_prs, now)
    prs_created_last_day = gh_search(f"repo:{REPO} is:pr created:>={cutoff}",
                                     label="PRs created in last 24h (any state)")

    # --- Open issues (REST /issues returns issues AND PRs; filter PRs out) ---
    log("[2/4] Fetching open issues...")
    open_issues_all = paginate(f"/repos/{REPO}/issues", {"state": "open"}, label="open issues")
    open_issues = [i for i in open_issues_all if "pull_request" not in i]
    log(f"  -> {len(open_issues)} open issues (out of {len(open_issues_all)} items incl. PRs)")
    n_is, avg_is_age, max_is_age = ages_stats(open_issues, now)
    issues_created_last_day = gh_search(f"repo:{REPO} is:issue created:>={cutoff}",
                                        label="issues created in last 24h (any state)")

    # --- Closed in the last 24h (search API) ---
    log("[3/4] Searching closed-in-last-24h counts (search API)...")
    accepted_prs = gh_search(f"repo:{REPO} is:pr is:merged merged:>={cutoff}",
                             label="accepted (merged) PRs")
    rejected_prs = gh_search(f"repo:{REPO} is:pr -is:merged closed:>={cutoff}",
                            label="rejected (closed unmerged) PRs")
    issues_closed = gh_search(f"repo:{REPO} is:issue closed:>={cutoff}",
                             label="closed issues")
    log("[4/4] Done.")

    sections = [
        ("Pull Requests", [
            ("Current number of Open PRs", n_prs),
            ("Change Requests created in the last day", prs_created_last_day),
            ("Accepted PRs in the past day", accepted_prs),
            ("Rejected PRs in the past day", rejected_prs),
            ("Average age of open PRs", fmt_days(avg_pr_age)),
            ("Age of the oldest open PR", fmt_days(max_pr_age)),
        ]),
        ("Issues", [
            ("Issues in Open state", n_is),
            ("Issues created in the past day", issues_created_last_day),
            ("Issues closed in the past day", issues_closed),
            ("Average age of open issues", fmt_days(avg_is_age)),
            ("Age of the oldest open issue", fmt_days(max_is_age)),
        ]),
    ]
    for title, rows in sections:
        print(f"{title}:")
        for label, value in rows:
            print(f"  {label:<40} {value}")
        print("-" * 60)
    print("(ages over currently-open items; 'created/closed' = trailing 24h window)")


if __name__ == "__main__":
    main()
