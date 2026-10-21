# oss-metrics

## Creating fake data (metrics ground truth)

Generate fake activity on a repository - PRs that modify `src/samplecode.py`
and fake issues - and log every action to a CSV that can be used as ground
truth for the metrics above:

```bash
./create_fake_data.py 5 5 org/ospo-repo-sandbox             # 5 PRs, 5 issues, all left open
./create_fake_data.py 3 3 org/ospo-repo-sandbox --seed 42   # reproducible fake data
```

Options: `--path` (sample file, default `src/samplecode.py`), `--csv` (log
path, default `fake_data_log.csv`), `--seed`. All created PRs and issues are
left open.

Each action appends a row to the CSV (`timestamp_utc`, `repo`, `action`,
`kind`, `number`, `title`, `branch`, `url`, `state_after`, `detail`), e.g.
`pr_opened` / `issue_opened`. Counting rows within a time window yields the
expected values for the metrics measured by `github_repo_health.py`.

The token (same resolution order as above) needs push access to the target
repo.

## Run

```bash
./github_repo_health.py                  # defaults to DataDog/datadog-agent
./github_repo_health.py owner/repo       # any other github repository
```

No dependencies (Python 3 stdlib only). Auth uses `GITHUB_TOKEN` /
`GH_TOKEN` env vars, falling back to `gh auth token`. Progress goes to stderr,
results to stdout. Takes ~20-30s (paginates all open PRs/issues).

## Metrics

| Metric | Meaning |
|---|---|
| Current number of Open PRs | Open PRs right now |
| Change Requests created in the last day | PRs created < 24h ago (any state: open, merged, closed) |
| Accepted PRs in the past day | PRs merged < 24h ago |
| Rejected PRs in the past day | PRs closed unmerged < 24h ago |
| Average age of open PRs | Mean age of currently-open PRs |
| Age of the oldest PR | Oldest currently-open PR |
| Issues in Open state | Open issues (excludes PRs) |
| Issues created in the past day | Issues created < 24h ago (any state) |
| Issues closed in the past day | Issues closed < 24h ago |
| Average age of open issues | Mean age of currently-open issues |
| Age of the oldest open issue | Oldest currently-open issue |

