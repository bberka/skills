---
name: ci-optimize
description: "Makes a project's CI fast and measures the result. Reads the workflows, the run history, and the merge rules (GitHub rulesets and branch protection, GitLab merge settings), finds what developers actually wait on, applies the speedups that keep every check meaning the same thing, asks before any change that alters what is checked or how the app is built, and proves the gain with a before and after comparison from real runs. Sets CI up from scratch when the project has none. Use when the user asks to speed up, optimize, audit, or fix slow CI, pipelines, GitHub Actions, or GitLab CI, to cut CI minutes or cost, or to set up CI for a project. Don't use for a single failing job, for deploy or release design, or for CI security hardening."
argument-hint: "[scope, e.g. the test workflow, PR checks only, set up CI, report only]"
---

# CI optimize

Scope: $ARGUMENTS

(If that line is empty or still shows a placeholder, take the scope from the user's message. With no scope given, optimize what a pull request waits on.)

Make the wait from push to mergeable as short as the project allows, and prove it with numbers from real runs. The work is measurement first: most CI changes that look like speedups move nothing a developer waits on.

## Files in this skill

Paths are relative to the folder that holds this file. Read each file when its step says to.

| File | Read or run it when |
| --- | --- |
| `scripts/ci_timing.py` | Steps 2 and 7. `measure` samples run history, `rules` reads the merge rules, `compare` prints before and after. `--help` lists the flags. |
| [levers.md](levers.md) | Step 4, always. Every lever, how to spot it, and whether it is safe or needs a yes. |
| [github-actions.md](github-actions.md) | Steps 4 to 6, when the project uses GitHub Actions. |
| [gitlab-ci.md](gitlab-ci.md) | Steps 4 to 6, when the project uses GitLab CI. |
| [stacks.md](stacks.md) | Step 4. Read only the sections for the languages and tools the project uses. |
| `scripts/split_by_time.py` | When you shard tests by recorded time. Usage is in levers.md. |

## Words used here

- **Wait**: time from a push until the last check that blocks the merge has finished. This is the number to shrink.
- **Gate**: the checks that block a merge. The merge rules name them. With no rules, every check that runs on a pull request counts.
- **Pole**: the gate job that finishes last, with every job it waits on. Shortening anything else leaves the wait unchanged.
- **Floor**: the second-slowest chain. Once the pole drops below it, that chain is the new pole.
- **Runner minutes**: the sum of every job's run time, which is what the bill counts. A change can cut the wait and raise the minutes, or the reverse.

## Ground rules

- **Measure, then change, then measure again.** A lever is kept when real runs show it helped. One that made no measurable difference is reverted, however sound it looked.
- **A check keeps its meaning.** After your change, the same code is checked for the same things and a failure still fails. Anything else is the user's decision (step 5).
- **The pole comes first.** Spend effort in the order the measurements give. Report cost-only savings separately from wait savings.
- **Read why before removing.** A slow step with a comment, a commit message, or an issue explaining it was chosen. Treat changing it as the user's decision.
- **Every gate check still reports.** A required check that stops reporting blocks every pull request. Step 6 covers this.
- **Look tools and versions up.** Action versions, tool flags, and runner images change monthly. Check the current docs or `--help` before writing one into a workflow; the reference files name families of tools, and the project's lockfile and the docs name the version.
- **Touch only CI.** Workflow files, CI scripts, and tool config that CI reads. App code and merge rules change only with a yes.

## Steps

### 1. Find the CI and the stack

Find the provider and the config: `.github/workflows/`, `.gitlab-ci.yml` and its includes, and for anything else (CircleCI, Azure Pipelines, Jenkins, Buildkite) the config that exists. The scripts cover GitHub and GitLab. On another provider, read timings from its own CLI or API and apply levers.md, which is provider-neutral.

Note the languages, package managers, test runners, build tools, and whether it is a monorepo. Note which commands CI runs and where they are defined (`package.json` scripts, `Makefile`, `justfile`).

**No CI at all:** go to "Setting CI up from scratch" below.

Done when you can name the provider, every workflow that runs on a pull request, and the commands each job runs.

### 2. Measure the baseline

```bash
python3 scripts/ci_timing.py rules
python3 scripts/ci_timing.py measure --out <scratch>/before.json
```

`measure` samples recent passing pull request commits and prints the wait, the runner minutes, each job's median time and how often it finished last, and the step times of the slowest jobs. Pass `--event push --branch <default>` to see the default branch, `--event ''` for everything.

`rules` prints the gate: required checks, whether the branch must be up to date, the merge queue, and required approvals. If it reports something it could not read, say so and ask the user for the rules; a guess here can block every merge.

If the tools are missing or not signed in (`gh`, or a GitLab token), tell the user what to install or run, and stop unless they ask for a config-only review. A config-only review cannot rank anything by time, so its report says so at the top.

Fewer than five samples is a rough reading. Say that wherever you quote the numbers.

Done when you have the baseline file, the gate, and the pole with its step times.

### 3. Read the intent

Before judging any job, read the comments in the workflow files and the history of the CI config (`git log --oneline -15 -- <ci paths>`, then `git show` for commits that touch what you plan to change). Read the contributor docs where they describe CI. Record each deliberate choice you find: "packages build only after tests pass", "full history needed for versioning".

Done when every job on the pole has either a known reason for its shape or a note that none was written down.

### 4. Find the levers

Read [levers.md](levers.md), the provider file, and the matching sections of [stacks.md](stacks.md). Walk the pole from its slowest step down, then the floor, then the rest for cost.

For each candidate write one line: what changes, the measured time it targets, the saving you expect on the wait and on runner minutes, and its class from levers.md (safe or ask). Size every saving from the step times you measured. "Caching speeds up installs" is not a size; "install takes 48s of a 2m10s pole job, a warm cache should leave about 10s" is.

When a job's step times don't explain where the time goes, read the log of one median run before guessing.

Done when the pole and the floor each have their candidates listed with sizes, or a line saying nothing can shorten them and why.

### 5. Ask before the changes that are not yours to make

Safe changes go ahead without a question. Stop and ask about a candidate when it:

- changes **what is checked**: fewer tests on a pull request, a lint or type tool swapped for one with different rules, a platform or version dropped from a matrix, a job made optional
- changes **when it is checked**: moved from pull requests to the default branch, a nightly run, or a merge queue
- changes **the app or its build**: a bundler, compiler flags, test isolation settings, dependency versions, anything users of the app could notice
- is a **large refactor**: restructuring the test suite, splitting packages, more than a few files outside CI config
- changes **merge rules or provider settings**: required checks, rulesets, merge queue, runner types
- **costs money**: larger runners, paid cache or remote-build services, a clear rise in runner minutes

Ask once, with every such candidate in one question: what it is, the measured saving, what gets weaker or what it costs, and the guardrail you would add (levers.md names one for each). Recommend for or against each. Then apply only what the user approved.

If the user is away and told you to carry on, apply the safe changes only and put the rest in the report as open decisions with their sizes.

Done when every candidate is either safe, approved, declined, or listed as an open decision.

### 6. Apply

Work on a new branch. Use a git worktree when the user's working tree has uncommitted changes.

- One lever per commit, so each can be measured and reverted on its own.
- Run what you can locally before pushing: the changed commands themselves, and a workflow linter (`actionlint` for GitHub, `glab ci lint` or the CI Lint API for GitLab) when one is installed.
- Keep the gate intact. For each required check name from step 2, confirm a job with exactly that name still runs and reports on every pull request, including pull requests that your path filters skip. The provider file explains which skips report as passed and which leave the check pending forever. If a required name has to change, that is a merge-rule change: ask.
- Keep comments in the workflow true. Update the ones your change makes wrong.

Done when the branch holds the approved changes, local checks pass, and every required check name is accounted for.

### 7. Measure the result

Real numbers need real runs, which needs a push and usually a pull request. Pushing and opening a pull request are the user's call: do it when they asked for it or agree now.

1. Push and let CI finish. If a check fails, fix it before measuring; a red run measures nothing.
2. Run it at least twice more (re-run the workflow or push an empty commit). The first run after a cache change is cold and slower than every run after it. Three warm runs are a fair sample.
3. Measure and compare:

   ```bash
   python3 scripts/ci_timing.py measure --branch <your branch> --out <scratch>/after.json
   python3 scripts/ci_timing.py compare <scratch>/before.json <scratch>/after.json
   ```

4. Check the comparison is fair. Both sides must run the same jobs: a baseline of pull requests that skipped half the jobs through path filters is not comparable, so narrow it with `--workflow`, `--branch`, or `--sha` to commits that ran what your branch ran, and re-measure the baseline that way. Say which runs are cold.
5. Revert each lever that shows no gain, or that made its job slower. Caches are the usual case: on a fast network, restoring a large cache can take longer than the download it replaces.

Done when the comparison is from at least two warm runs with every gate check green, and each kept lever shows its gain in the job it touched.

### 8. Report

Answer in the chat, in this order. Keep it short; the table carries the result.

1. **The result in one sentence**: the wait before and after, and the runner minutes before and after.
2. **The comparison table** from `compare`, with the sample sizes and which runs were cold.
3. **What changed**, one line per kept lever with its measured gain.
4. **What was tried and dropped**, one line each with the measurement that ruled it out.
5. **Open decisions**: each ask-first candidate not yet approved, with its saving and its cost, biggest first.
6. **What is left**: the new pole and why it cannot go lower without one of the open decisions. If CI was already fast (a wait under about two minutes with nothing wasteful on the pole), say that and recommend leaving it alone.

Link the pull request when there is one. Leave merging to the user.

In report-only scope, stop after step 5's candidate list and present it in this format without sections 2 to 4.

## Setting CI up from scratch

1. List the checks the project already has as local commands: format, lint, typecheck, test, build. Don't invent checks the project doesn't run locally; propose a missing one (no tests, no linter) as a suggestion in the report.
2. Ask one question: which provider if the remote doesn't settle it, and which checks should block a merge.
3. Write the config with the layout from levers.md applied from the start: independent checks as parallel jobs, dependency cache keyed on the lockfile, superseded runs cancelled, a timeout on every job, least-privilege permissions, path filters only where a required check still reports. The provider file has a starting skeleton.
4. Run every command locally first. A CI that is red on its first run teaches nothing about speed.
5. Push, measure with `ci_timing.py`, and report the wait. Suggest merge rules that require the gate checks, and apply them only with a yes.
