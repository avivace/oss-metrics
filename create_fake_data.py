#!/usr/bin/env python3
"""create_fake_data.py - generate fake GitHub activity for metrics ground truth.

Creates fake PRs (each modifies `src/samplecode.py`) and fake issues on the
given repository. Every action is appended to a CSV log (default:
fake_data_log.csv) that can be used as ground truth to verify the metrics
measured by `github_repo_health.py`.

Usage:
    ./create_fake_data.py <n_prs> <n_issues> <owner/repo> [options]

Examples:
    ./create_fake_data.py 5 5 DataDog/ospo-repo-sandbox
    ./create_fake_data.py 3 3 DataDog/ospo-repo-sandbox --seed 42

All created PRs and issues are left open (no merging or closing, yet).

Token: GITHUB_TOKEN or GH_TOKEN env var, else falls back to `gh auth token`.
The token needs push access to the target repo.
Dependencies: none (stdlib only).
"""

import argparse
import base64
import csv
import json
import os
import random
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
DEFAULT_SAMPLE_PATH = "src/samplecode.py"
DEFAULT_CSV = "fake_data_log.csv"
CSV_COLUMNS = [
    "timestamp_utc",
    "repo",
    "action",        # pr_opened | issue_opened
    "kind",          # pr | issue
    "number",
    "title",
    "branch",        # set for PRs, empty for issues
    "url",
    "state_after",   # open | failed
    "detail",
]

ISSUE_TEMPLATES = [
    "sample calculation returns wrong result for negative inputs",
    "flaky test in samplecode tests",
    "docs for samplecode.py are outdated",
    "samplecode crashes on empty input",
    "samplecode logging is too verbose",
    "add input validation to samplecode",
    "samplecode helper is not reusable",
    "CI fails intermittently on samplecode lint",
]


def get_token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except Exception:
        return None


class GitHub:
    def __init__(self, token: str | None):
        self.headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "repo-health-script",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        else:
            print("warning: no GitHub token found", file=sys.stderr)

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        headers = dict(self.headers)
        if data:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read()).get("message", "")
            except Exception:
                detail = ""
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail}") from e

    def get_or_none(self, path: str) -> dict | None:
        try:
            return self.request("GET", path)
        except RuntimeError as e:
            if "HTTP 404" in str(e):
                return None
            raise


class GroundTruthLog:
    def __init__(self, path: str):
        self.path = path
        self.new_file = not os.path.exists(path)

    def log(self, action: str, kind: str, number: str, title: str, branch: str,
            url: str, state_after: str, detail: str, repo: str) -> None:
        row = {
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "repo": repo,
            "action": action,
            "kind": kind,
            "number": number,
            "title": title,
            "branch": branch,
            "url": url,
            "state_after": state_after,
            "detail": detail,
        }
        file_exists = os.path.exists(self.path)
        with open(self.path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        print(f"  [log] {action:<13} #{number} -> {state_after}: {detail}")


def sample_addition(run_id: str, idx: int, rng: random.Random) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        f"\n# fake update {run_id}-{idx} at {now}\n"
        f"SAMPLE_{run_id}_{idx} = {rng.randint(0, 1000)}\n"
    )


def create_pr(gh: GitHub, repo: str, base_branch: str, sample_path: str,
              run_id: str, idx: int, rng: random.Random) -> tuple[dict, str, str]:
    """Create one PR touching sample_path. Returns (pr, branch, commit_sha)."""
    # Fresh default-branch head each time.
    head_sha = gh.request(
        "GET", f"/repos/{repo}/git/ref/heads/{base_branch}"
    )["object"]["sha"]
    tree_sha = gh.request("GET", f"/repos/{repo}/git/commits/{head_sha}")["tree"]["sha"]

    current = gh.get_or_none(
        f"/repos/{repo}/contents/{urllib.parse.quote(sample_path)}?ref={base_branch}"
    )
    if current is None:
        content = f'"""Sample code, modified by fake-data generator run {run_id}."""\n'
        detail = "created sample file"
    else:
        content = base64.b64decode(current["content"]).decode()
        detail = "modified sample file"
    content += sample_addition(run_id, idx, rng)

    blob_sha = gh.request(
        "POST", f"/repos/{repo}/git/blobs", {"content": content, "encoding": "utf-8"}
    )["sha"]
    new_tree = gh.request("POST", f"/repos/{repo}/git/trees", {
        "base_tree": tree_sha,
        "tree": [{"path": sample_path, "mode": "100644", "type": "blob", "sha": blob_sha}],
    })["sha"]
    commit_sha = gh.request("POST", f"/repos/{repo}/git/commits", {
        "message": f"fake data update {run_id}-{idx}",
        "tree": new_tree,
        "parents": [head_sha],
    })["sha"]

    branch = f"fake-data/{run_id}/pr-{idx}"
    gh.request("POST", f"/repos/{repo}/git/refs", {
        "ref": f"refs/heads/{branch}",
        "sha": commit_sha,
    })
    pr = gh.request("POST", f"/repos/{repo}/pulls", {
        "title": f"Fake data update {run_id}-{idx}",
        "head": branch,
        "base": base_branch,
        "body": f"Automated fake data update {run_id}-{idx} ({detail}).",
    })
    return pr, branch, commit_sha


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create fake GitHub activity (PRs + issues) for metrics ground truth.",
    )
    parser.add_argument("n_prs", type=int, help="number of PRs to open")
    parser.add_argument("n_issues", type=int, help="number of issues to open")
    parser.add_argument("repo", help="target repository as owner/repo")
    parser.add_argument("--path", default=DEFAULT_SAMPLE_PATH,
                        help=f"sample file modified by each PR (default: {DEFAULT_SAMPLE_PATH})")
    parser.add_argument("--csv", default=DEFAULT_CSV,
                        help=f"ground-truth CSV log path (default: {DEFAULT_CSV})")
    parser.add_argument("--seed", type=int, default=None,
                        help="random seed for reproducible fake data")
    args = parser.parse_args()

    if args.n_prs < 0 or args.n_issues < 0:
        sys.exit("error: counts must be >= 0")

    rng = random.Random(args.seed)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    gh = GitHub(get_token())
    log = GroundTruthLog(args.csv)

    repo_info = gh.request("GET", f"/repos/{args.repo}")
    base_branch = repo_info["default_branch"]
    print(f"repo:          {args.repo} (default branch: {base_branch})")
    print(f"fake PRs:      {args.n_prs}")
    print(f"fake issues:   {args.n_issues}")
    print(f"sample file:   {args.path}")
    print(f"ground truth:  {args.csv}")
    print("-" * 60)

    # --- PRs ---
    for idx in range(1, args.n_prs + 1):
        print(f"[PR {idx}/{args.n_prs}] creating...")
        try:
            pr, branch, _ = create_pr(gh, args.repo, base_branch, args.path,
                                      run_id, idx, rng)
        except RuntimeError as e:
            log.log("pr_opened", "pr", "", f"fake data update {run_id}-{idx}", "",
                    "", "failed", str(e), args.repo)
            continue
        log.log("pr_opened", "pr", str(pr["number"]), pr["title"], branch,
                pr["html_url"], "open", "PR opened", args.repo)
        time.sleep(1)

    # --- Issues ---
    for idx in range(1, args.n_issues + 1):
        title = f"[fake {run_id}-{idx}] {rng.choice(ISSUE_TEMPLATES)}"
        print(f"[issue {idx}/{args.n_issues}] creating: {title}")
        try:
            issue = gh.request("POST", f"/repos/{args.repo}/issues", {
                "title": title,
                "body": f"Automated fake issue {run_id}-{idx}. "
                        f"Reported value: {rng.randint(0, 1000)}.",
            })
        except RuntimeError as e:
            log.log("issue_opened", "issue", "", title, "", "",
                    "failed", str(e), args.repo)
            continue
        log.log("issue_opened", "issue", str(issue["number"]), title, "",
                issue["html_url"], "open", "issue opened", args.repo)
        time.sleep(1)

    print("-" * 60)
    print(f"done. ground truth written to {args.csv}")
    print("verify with: ./github_repo_health.py " + args.repo)


if __name__ == "__main__":
    main()
