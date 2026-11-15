#!/usr/bin/env python3
"""Measure CI from run history, read merge rules, and compare two measurements.

  ci_timing.py measure [--repo R] [--event pull_request] [--branch B]
                       [--exclude-branch B] [--workflow NAME] [--sha SHA]
                       [--limit 15] [--out FILE]
  ci_timing.py rules   [--repo R] [--branch B]
  ci_timing.py compare BEFORE.json AFTER.json

GitHub goes through the `gh` CLI. GitLab goes through its REST API, with a token
from GITLAB_TOKEN or `glab` when the project is private. Only reads; standard
library only. `--repo` defaults to the origin remote of the current directory.
"""

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime


def die(msg):
    sys.exit(f"ci_timing: {msg}")


def ts(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def p50(values):
    return statistics.median(values) if values else 0.0


def p90(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]


def fmt(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def detect(repo_arg, provider_arg, host_arg):
    """Return (provider, host, 'owner/name')."""
    if repo_arg and not repo_arg.startswith(("http", "git@")):
        provider = provider_arg or "github"
        host = host_arg or ("gitlab.com" if provider == "gitlab" else "github.com")
        return provider, host, repo_arg
    url = repo_arg
    if not url:
        try:
            url = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            die("no --repo given and no origin remote here")
    match = re.match(r"(?:https?://|ssh://git@|git@)([^/:]+)[/:](.+?)(?:\.git)?/?$", url)
    if not match:
        die(f"cannot read a repository from {url!r}")
    host, path = match.group(1), match.group(2)
    provider = provider_arg or ("github" if "github" in host else "gitlab")
    return provider, host_arg or host, path


# ---------- GitHub ----------

def gh(path, host):
    cmd = ["gh", "api", path]
    if host != "github.com":
        cmd += ["--hostname", host]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        die("the gh CLI is not installed (https://cli.github.com), so GitHub run history is unreachable")
    if out.returncode != 0:
        return None, out.stderr.strip()
    return json.loads(out.stdout), None


def github_runs(repo, host, args):
    query = {"per_page": "100", "status": "completed"}
    if args.event:
        query["event"] = args.event
    if args.branch:
        query["branch"] = args.branch
    if len(args.sha) == 1:
        query["head_sha"] = args.sha[0]
    data, err = gh(f"repos/{repo}/actions/runs?{urllib.parse.urlencode(query)}", host)
    if data is None:
        die(f"could not list runs: {err}")
    runs = data.get("workflow_runs", [])
    conclusions = {}
    for run in runs:
        conclusions[run["conclusion"]] = conclusions.get(run["conclusion"], 0) + 1
    groups, order = {}, []
    for run in runs:
        if run["head_branch"] in args.exclude_branch:
            continue
        if args.workflow and run["name"] not in args.workflow:
            continue
        if args.sha and not any(run["head_sha"].startswith(sha) for sha in args.sha):
            continue
        # One sample per commit and event: a scheduled run days later is a different wait.
        key = (run["head_sha"], run["event"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(run)
    samples = []
    for key in order:
        group = groups[key]
        # A commit counts once every workflow it started has passed.
        if any(r["conclusion"] not in ("success", "skipped") for r in group):
            continue
        jobs = []
        for run in group:
            if run["conclusion"] != "success":
                continue
            data, err = gh(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100", host)
            if data is None:
                die(f"could not list jobs of run {run['id']}: {err}")
            for job in data["jobs"]:
                if job["conclusion"] != "success" or not job.get("started_at"):
                    continue
                steps = [
                    {"name": s["name"], "seconds": ts(s["completed_at"]) - ts(s["started_at"])}
                    for s in job.get("steps", [])
                    if s.get("started_at") and s.get("completed_at") and s["conclusion"] == "success"
                ]
                jobs.append({
                    "workflow": run["name"],
                    "name": job["name"],
                    "created": ts(job["created_at"]),
                    "started": ts(job["started_at"]),
                    "completed": ts(job["completed_at"]),
                    "runner": ",".join(job.get("labels") or []),
                    "steps": steps,
                })
        if not jobs:
            continue
        samples.append({
            "sha": key[0],
            "branch": group[0]["head_branch"],
            "start": min(ts(r["run_started_at"] or r["created_at"]) for r in group),
            "jobs": jobs,
        })
        if len(samples) >= args.limit:
            break
    return samples, conclusions


def github_rules(repo, host, branch):
    info, err = gh(f"repos/{repo}", host)
    if info is None:
        die(f"could not read the repository: {err}")
    branch = branch or info["default_branch"]
    result = {
        "provider": "github", "branch": branch, "required_checks": [], "strict": False,
        "merge_queue": False, "required_reviews": None, "sources": [], "unreadable": [],
        "merge_methods": [m for m in ("merge", "squash", "rebase") if info.get(f"allow_{m}_commit" if m != "rebase" else "allow_rebase_merge")],
    }
    rules, err = gh(f"repos/{repo}/rules/branches/{urllib.parse.quote(branch, safe='')}", host)
    if rules is None:
        result["unreadable"].append(f"rulesets: {err}")
    else:
        for rule in rules:
            params = rule.get("parameters") or {}
            source = f"ruleset {rule.get('ruleset_id')}"
            if rule["type"] == "required_status_checks":
                result["required_checks"] += [c["context"] for c in params.get("required_status_checks", [])]
                result["strict"] = result["strict"] or params.get("strict_required_status_checks_policy", False)
                result["sources"].append(source)
            elif rule["type"] == "merge_queue":
                result["merge_queue"] = True
            elif rule["type"] == "pull_request":
                result["required_reviews"] = params.get("required_approving_review_count")
            elif rule["type"] == "workflows":
                result["required_checks"] += [f"workflow:{w.get('path')}" for w in params.get("workflows", [])]
                result["sources"].append(source)
    legacy, err = gh(f"repos/{repo}/branches/{urllib.parse.quote(branch, safe='')}/protection", host)
    if legacy is None:
        if "Branch not protected" not in err and "404" not in err:
            result["unreadable"].append(f"branch protection: {err}")
    else:
        checks = legacy.get("required_status_checks") or {}
        result["required_checks"] += checks.get("contexts", [])
        result["strict"] = result["strict"] or checks.get("strict", False)
        if checks:
            result["sources"].append("branch protection")
        reviews = legacy.get("required_pull_request_reviews")
        if reviews and result["required_reviews"] is None:
            result["required_reviews"] = reviews.get("required_approving_review_count")
    result["required_checks"] = sorted(set(result["required_checks"]))
    return result


# ---------- GitLab ----------

def gitlab_token():
    token = os.environ.get("GITLAB_TOKEN") or os.environ.get("GITLAB_PRIVATE_TOKEN")
    if token:
        return token
    try:
        out = subprocess.run(["glab", "config", "get", "token"], capture_output=True, text=True)
        return out.stdout.strip() or None
    except FileNotFoundError:
        return None


def gitlab(path, host, token):
    request = urllib.request.Request(f"https://{host}/api/v4/{path}")
    if token:
        request.add_header("PRIVATE-TOKEN", token)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read()), None
    except urllib.error.HTTPError as error:
        return None, f"HTTP {error.code}"
    except urllib.error.URLError as error:
        return None, str(error.reason)


def gitlab_runs(repo, host, args):
    token = gitlab_token()
    project = urllib.parse.quote(repo, safe="")
    query = {"per_page": "100"}
    if args.event:
        # GitHub's event names are accepted so one command line works on both.
        query["source"] = {"pull_request": "merge_request_event"}.get(args.event, args.event)
    if args.branch:
        query["ref"] = args.branch
    if len(args.sha) == 1:
        query["sha"] = args.sha[0]
    pipelines, err = gitlab(f"projects/{project}/pipelines?{urllib.parse.urlencode(query)}", host, token)
    if pipelines is None:
        die(f"could not list pipelines ({err}); set GITLAB_TOKEN for a private project")
    conclusions = {}
    for pipeline in pipelines:
        conclusions[pipeline["status"]] = conclusions.get(pipeline["status"], 0) + 1
    samples = []
    for pipeline in pipelines:
        if pipeline["status"] != "success" or pipeline["ref"] in args.exclude_branch:
            continue
        if args.sha and not any(pipeline["sha"].startswith(sha) for sha in args.sha):
            continue
        data, err = gitlab(f"projects/{project}/pipelines/{pipeline['id']}/jobs?per_page=100", host, token)
        if data is None:
            die(f"could not list jobs of pipeline {pipeline['id']}: {err}")
        jobs = [
            {
                "workflow": job["stage"], "name": job["name"], "created": ts(job["created_at"]),
                "started": ts(job["started_at"]), "completed": ts(job["finished_at"]),
                "queued": job.get("queued_duration"),
                "runner": ",".join(job.get("tag_list") or []), "steps": [],
            }
            for job in data
            if job["status"] == "success" and job.get("started_at") and job.get("finished_at")
        ]
        if not jobs:
            continue
        samples.append({
            "sha": pipeline["sha"], "branch": pipeline["ref"],
            "start": ts(pipeline["created_at"]), "jobs": jobs,
        })
        if len(samples) >= args.limit:
            break
    return samples, conclusions


def gitlab_rules(repo, host, branch):
    token = gitlab_token()
    project = urllib.parse.quote(repo, safe="")
    info, err = gitlab(f"projects/{project}", host, token)
    if info is None:
        die(f"could not read the project ({err}); set GITLAB_TOKEN for a private project")
    branch = branch or info["default_branch"]
    result = {
        "provider": "gitlab", "branch": branch, "required_checks": [], "strict": False,
        "merge_queue": bool(info.get("merge_trains_enabled")), "required_reviews": None,
        "sources": [], "unreadable": [], "merge_methods": [info.get("merge_method")],
        "pipeline_must_succeed": info.get("only_allow_merge_if_pipeline_succeeds"),
        "skipped_pipeline_counts_as_success": info.get("allow_merge_on_skipped_pipeline"),
        "merge_pipelines": info.get("merge_pipelines_enabled"),
    }
    if result["pipeline_must_succeed"]:
        # GitLab gates on the whole pipeline: every job without allow_failure is required.
        result["required_checks"] = ["<every job without allow_failure>"]
        result["sources"].append("project setting: pipelines must succeed")
    result["strict"] = info.get("merge_method") in ("ff", "rebase_merge")
    if info.get("only_allow_merge_if_pipeline_succeeds") is None:
        result["unreadable"].append("merge settings need a token with read_api")
    approvals, err = gitlab(f"projects/{project}/approvals", host, token)
    if approvals is not None:
        result["required_reviews"] = approvals.get("approvals_before_merge")
    return result


# ---------- Reports ----------

def summarize(samples, conclusions, required, meta):
    walls, minutes, billed = [], [], []
    jobs, workflows = {}, {}
    for sample in samples:
        end = max(j["completed"] for j in sample["jobs"])
        walls.append(end - sample["start"])
        minutes.append(sum(j["completed"] - j["started"] for j in sample["jobs"]) / 60)
        billed.append(sum(math.ceil((j["completed"] - j["started"]) / 60) for j in sample["jobs"]))
        last = max(sample["jobs"], key=lambda j: j["completed"])
        seen_workflows = {}
        for job in sample["jobs"]:
            key = f"{job['workflow']} / {job['name']}"
            entry = jobs.setdefault(key, {"durations": [], "queues": [], "last": 0, "runner": job["runner"], "steps": {}})
            entry["durations"].append(job["completed"] - job["started"])
            queued = job.get("queued")
            entry["queues"].append(queued if queued is not None else max(0.0, job["started"] - job["created"]))
            if job is last:
                entry["last"] += 1
            for step in job["steps"]:
                entry["steps"].setdefault(step["name"], []).append(step["seconds"])
            span = seen_workflows.setdefault(job["workflow"], [job["created"], job["completed"]])
            span[0], span[1] = min(span[0], job["created"]), max(span[1], job["completed"])
        for name, span in seen_workflows.items():
            entry = workflows.setdefault(name, {"walls": [], "last": 0})
            entry["walls"].append(span[1] - sample["start"])
            if name == last["workflow"]:
                entry["last"] += 1

    def is_required(key, name):
        return any(c == name or c == key or name.startswith(c + " (") for c in required)

    job_rows = [
        {
            "job": key, "runs": len(e["durations"]), "p50": p50(e["durations"]), "p90": p90(e["durations"]),
            "queue_p50": p50(e["queues"]), "last_to_finish": e["last"], "runner": e["runner"],
            "required": is_required(key, key.split(" / ", 1)[1]),
            "steps": sorted(
                ({"step": name, "p50": p50(values)} for name, values in e["steps"].items()),
                key=lambda s: -s["p50"],
            ),
        }
        for key, e in jobs.items()
    ]
    job_rows.sort(key=lambda r: (-r["last_to_finish"], -r["p50"]))
    return {
        **meta,
        "commits": len(samples),
        "conclusions": conclusions,
        "wall_p50": p50(walls), "wall_p90": p90(walls),
        "runner_minutes_p50": p50(minutes), "billed_minutes_p50": p50(billed),
        "required_checks": required,
        "workflows": sorted(
            ({"workflow": n, "runs": len(e["walls"]), "wall_p50": p50(e["walls"]), "last_to_finish": e["last"]}
             for n, e in workflows.items()),
            key=lambda r: -r["wall_p50"],
        ),
        "jobs": job_rows,
    }


def print_measure(summary):
    n = summary["commits"]
    print(f"# CI timing: {summary['repo']} ({summary['provider']})")
    scope = [f"event={summary['event']}" if summary["event"] else "all events"]
    if summary["branch"]:
        scope.append(f"branch={summary['branch']}")
    if summary["sha"]:
        scope.append("sha=" + ",".join(sha[:9] for sha in summary["sha"]))
    print(f"\n{n} passing commits sampled ({', '.join(scope)}). Conclusions in the last 100 runs: "
          + ", ".join(f"{k} {v}" for k, v in sorted(summary["conclusions"].items(), key=lambda kv: -kv[1])))
    if n == 0:
        print("\nNo passing runs matched. Widen --event or --branch, or raise --limit.")
        return
    if n < 5:
        print(f"\nOnly {n} samples: treat every number below as a rough reading.")
    print(f"\n- Wait from push to last check done: p50 {fmt(summary['wall_p50'])}, p90 {fmt(summary['wall_p90'])}")
    print(f"- Runner time per commit: p50 {summary['runner_minutes_p50']:.1f} min "
          f"(billed as {summary['billed_minutes_p50']:.0f} min, each job rounded up)")
    required = summary["required_checks"]
    print(f"- Required checks: {', '.join(required) if required else 'none found'}")
    print("\n## Workflows (stages on GitLab)\n")
    print("| Workflow | Runs | Done after push (p50) | Last to finish |")
    print("| --- | --- | --- | --- |")
    for row in summary["workflows"]:
        print(f"| {row['workflow']} | {row['runs']} | {fmt(row['wall_p50'])} | {row['last_to_finish']}/{n} |")
    print("\n## Jobs\n")
    print("| Job | Runs | p50 | p90 | Queue p50 | Last to finish | Required |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for row in summary["jobs"]:
        print(f"| {row['job']} | {row['runs']} | {fmt(row['p50'])} | {fmt(row['p90'])} | {fmt(row['queue_p50'])} "
              f"| {row['last_to_finish']}/{n} | {'yes' if row['required'] else ''} |")
    print("\n## Steps of the slowest jobs (p50)\n")
    shown = sorted(summary["jobs"], key=lambda r: -r["p50"])[:4]
    for row in shown:
        if not row["steps"]:
            continue
        parts = [f"{s['step']} {fmt(s['p50'])}" for s in row["steps"][:6] if s["p50"] >= 1]
        print(f"- **{row['job']}** ({fmt(row['p50'])}): " + "; ".join(parts))
    if not any(row["steps"] for row in shown):
        print("This provider's API has no step timings. Read a job log for the split.")


def delta(before, after, unit):
    if before == 0:
        return "new"
    change = (after - before) / before * 100
    diff = after - before
    text = fmt(abs(diff)) if unit == "s" else f"{abs(diff):.1f} min"
    return f"{'-' if diff < 0 else '+'}{text} ({change:+.0f}%)"


def print_compare(before, after):
    print("# CI before and after\n")
    print(f"Before: {before['commits']} commits ({before.get('branch') or 'all branches'}). "
          f"After: {after['commits']} commits ({after.get('branch') or 'all branches'}).")
    if min(before["commits"], after["commits"]) < 3:
        print("Fewer than 3 samples on one side: a single cold cache or slow runner can swing these numbers.")
    queue_before = max((row["queue_p50"] for row in before["jobs"]), default=0)
    queue_after = max((row["queue_p50"] for row in after["jobs"]), default=0)
    if max(queue_before, queue_after) > 30:
        print(f"Jobs waited for a runner (longest median queue: before {fmt(queue_before)}, after {fmt(queue_after)}). "
              "The wait rows include that queue. Judge each change by its job and step times, which do not.")
    print("\n| | Before | After | Change |")
    print("| --- | --- | --- | --- |")
    for label, key in (("Wait, push to last check (p50)", "wall_p50"), ("Wait (p90)", "wall_p90")):
        print(f"| {label} | {fmt(before[key])} | {fmt(after[key])} | {delta(before[key], after[key], 's')} |")
    for label, key in (("Runner minutes per commit (p50)", "runner_minutes_p50"), ("Billed minutes per commit (p50)", "billed_minutes_p50")):
        print(f"| {label} | {before[key]:.1f} | {after[key]:.1f} | {delta(before[key], after[key], 'min')} |")
    old = {row["job"]: row for row in before["jobs"]}
    new = {row["job"]: row for row in after["jobs"]}
    print("\n| Job | Before p50 | After p50 | Change |")
    print("| --- | --- | --- | --- |")
    for name in sorted(set(old) | set(new), key=lambda k: -max(old.get(k, {}).get("p50", 0), new.get(k, {}).get("p50", 0))):
        b, a = old.get(name), new.get(name)
        if b and a:
            print(f"| {name} | {fmt(b['p50'])} | {fmt(a['p50'])} | {delta(b['p50'], a['p50'], 's')} |")
        elif b:
            print(f"| {name} | {fmt(b['p50'])} | gone | |")
        else:
            print(f"| {name} | new | {fmt(a['p50'])} | |")
    lost = [c for c in before.get("required_checks", []) if not c.startswith(("<", "workflow:"))
            and not any(row["required"] for row in after["jobs"] if c in row["job"])]
    if lost:
        print("\n**Required checks with no passing job in the after sample:** " + ", ".join(lost)
              + ". A pull request cannot merge until each one reports.")


def print_rules(rules):
    print(f"# Merge rules for {rules['branch']} ({rules['provider']})\n")
    checks = rules["required_checks"]
    print(f"- Required checks: {', '.join(checks) if checks else 'none'}"
          + (f" (from {', '.join(sorted(set(rules['sources'])))})" if rules["sources"] else ""))
    print(f"- Branch must be up to date before merging: {'yes' if rules['strict'] else 'no'}")
    print(f"- Merge queue: {'yes' if rules['merge_queue'] else 'no'}")
    print(f"- Required approvals: {rules['required_reviews'] if rules['required_reviews'] is not None else 'unknown'}")
    print(f"- Merge methods: {', '.join(str(m) for m in rules['merge_methods'])}")
    for key in ("pipeline_must_succeed", "skipped_pipeline_counts_as_success", "merge_pipelines"):
        if key in rules:
            print(f"- {key.replace('_', ' ').capitalize()}: {rules[key]}")
    for problem in rules["unreadable"]:
        print(f"- Could not read: {problem}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("measure", "rules"):
        command = sub.add_parser(name)
        command.add_argument("--repo", help="owner/name or a remote URL; defaults to the origin remote")
        command.add_argument("--provider", choices=["github", "gitlab"])
        command.add_argument("--host")
        command.add_argument("--branch")
    measure = sub.choices["measure"]
    measure.add_argument("--event", default="pull_request", help="'' for every event")
    measure.add_argument("--exclude-branch", action="append", default=[])
    measure.add_argument("--workflow", action="append", default=[],
                         help="GitHub only: count only this workflow (by name); repeat for several")
    measure.add_argument("--sha", action="append", default=[],
                         help="count only this commit; repeat to build a baseline from chosen commits (full SHAs)")
    measure.add_argument("--limit", type=int, default=15, help="passing commits to sample")
    measure.add_argument("--out", help="write the summary as JSON for `compare`")
    compare = sub.add_parser("compare")
    compare.add_argument("before")
    compare.add_argument("after")
    args = parser.parse_args()

    if args.command == "compare":
        with open(args.before) as a, open(args.after) as b:
            print_compare(json.load(a), json.load(b))
        return

    provider, host, repo = detect(args.repo, args.provider, args.host)
    if args.command == "rules":
        rules = github_rules(repo, host, args.branch) if provider == "github" else gitlab_rules(repo, host, args.branch)
        print_rules(rules)
        return

    rules = github_rules(repo, host, None) if provider == "github" else gitlab_rules(repo, host, None)
    samples, conclusions = (github_runs if provider == "github" else gitlab_runs)(repo, host, args)
    meta = {"repo": repo, "provider": provider, "event": args.event, "branch": args.branch, "sha": args.sha}
    summary = summarize(samples, conclusions, rules["required_checks"], meta)
    print_measure(summary)
    if args.out:
        with open(args.out, "w") as handle:
            json.dump(summary, handle, indent=1)
        print(f"\nSaved to {args.out}")


if __name__ == "__main__":
    main()
