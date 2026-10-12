# oss-metrics

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
| Change Requests created in the last day | PRs still open AND created < 24h ago |
| Accepted PRs in the past day | PRs merged < 24h ago |
| Rejected PRs in the past day | PRs closed unmerged < 24h ago |
| Average age of open PRs | Mean age of currently-open PRs |
| Age of the oldest PR | Oldest currently-open PR |
| Issues in Open state | Open issues (excludes PRs) |
| Issues created in the past day | Issues still open AND created < 24h ago |
| Issues closed in the past day | Issues closed < 24h ago |
| Average age of open issues | Mean age of currently-open issues |
| Age of the oldest open issue | Oldest currently-open issue |

