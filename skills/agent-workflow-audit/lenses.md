# Lenses

Eight ways to read the same evidence. For each: what it is, where the digest shows it, and the fix that usually fits. The fix ladder in SKILL.md decides the rung, and a finding counts only at the pattern bar: three or more sessions, or two or more people.

File names below are the outputs of `session_digest.py scan`.

## 1. Repeated asks

The developer types the same request session after session. Each one is a rule, a script, or a hook that does not exist yet.

Where to look: the recurring phrases and pasted blocks at the top of `prompts.md`, then the asks themselves, grouped by meaning (phrasing varies, and a developer may write in more than one language). A block the developer keeps pasting, such as a CI failure or an error from the running app, is an ask too: the agent should have fetched or prevented it.

| What recurs | Usual fix |
| --- | --- |
| A closing chore: "run lint and tests", "commit and push", "open a PR", "update the changelog" | A hook or check that runs it, or one project command that does the whole closing sequence |
| A standing preference: "use pnpm", "no comments", "keep it short" | One rule line. If the rule exists and is ignored, enforce it |
| Context pasted every time: how to start the app, which env file, where the logs are | A script that does it, and a pointer in the rules |
| The same multi-step task: a release, a migration, a dependency bump, a triage pass | A project skill or command, or a scheduled task |
| Model, effort, or mode instructions | A project default in the harness settings (ask first) |
| "Continue", "go on", "yes do it" after a pause the agent did not need | A rule on when to proceed without asking, or a permission list entry (ask first) |

Size it in asks per week and the characters typed. Count with `session_digest.py count` and read the weekly split: an ask that is fading after a rule change is already fixed, and one that came back is a rule that did not hold.

## 2. Corrections and repeated mistakes

The developer redirects work already done, and the same redirect comes back in other sessions.

Where to look: in each session digest, an ask that follows an assistant tail claiming completion or describing an approach. Classify by reading, not by keywords: praise with an exclamation mark is not frustration, and a calm "actually, use the other table" is a correction.

Kinds worth counting separately:

- **Reversal**: "undo that", "go back", a `git revert` or `git checkout --` right after an edit.
- **Wrong tool or command**: the agent used npm in a pnpm repo, the wrong test runner, a deprecated script.
- **Scope**: it changed more than asked, or stopped short of what was asked.
- **Convention**: naming, file placement, style, a pattern the codebase already has.
- **Forgotten step**: tests, types, docs, a migration, the second place a change belongs.

For each, check the rules. No rule: write one line, or better, make the wrong path fail. A rule exists and was ignored: it is buried, vague, contradicted elsewhere, or phrased as a prohibition. Move it up a rung instead of repeating it. When a skill's workflow caused the mistake, fix that skill.

Size it in corrections per session and the tokens spent between the mistake and its repair.

## 3. Token sinks

Where to look: `summary.md` for the largest outputs by command and by tool, the most-read files, tokens by model, and the share of sessions that compacted. Session digests for repeats and biggest results.

| Sink | Signal | Usual fix |
| --- | --- | --- |
| Loud commands | A test, build, install, or log command returning tens of thousands of characters per call | A quiet flag or reporter in the script, output to a file with a tail, a failures-only mode |
| Rereading | The same file read many times in a session, or the same large file in most sessions | A short map of that area in the docs, or split the file. Generated and lock files: a rule to search, not read |
| Rediscovery | Every session opens with the same exploration: listing folders, reading the same config, trying commands to find the right one | Cache what cannot be looked up in one step: the commands, the layout, the gotcha |
| Heavy rules | A large always-loaded size times every session | Prune, and move reference behind pointers |
| Retry loops | The identical failing call run again and again | Fix the cause, or a rule naming the right call |
| Model mismatch | The most expensive model doing renames, formatting, and lookups, or main-context reading that a cheap subagent could do | A default model per task kind, a delegation rule (ask first) |
| Long mixed sessions | Many unrelated asks in one session, compactions, a context that keeps growing | A developer habit: one task per session. Needs a human |
| Unused tools | MCP servers and skills loaded in every session and never called | Remove or scope them (ask first) |
| Cold cache | Cache writes high against cache reads, where the store records both | Long idle gaps or an unstable prompt prefix. Usually a habit or a harness setting |

Size it in characters or tokens per call, times calls, across the window. When several harnesses or models did the same kind of work, compare them: tokens and corrections per session, side by side.

## 4. Time sinks

Where to look: command seconds in `summary.md` and the session digests, session duration against active time, failed calls.

- **Slow checks run often**: the full suite after every edit when a targeted run would do. Fix: a documented targeted command, with the full run once at the end.
- **Setup failures**: a new worktree with no dependencies, no env file, a port in use, a missing tool, hit again in session after session. Fix: a setup script, a worktree hook.
- **Waiting on the developer**: permission prompts for harmless commands, questions the agent could have answered from the repo. Fix: a permission list (ask first), a rule on what to decide alone.
- **Serial work that could be parallel**: independent searches or checks run one after another.
- **Polling**: sleep loops and repeated status calls against CI or a deploy. Fix: a wait command or a watcher.
- **Hung commands**: a watcher, dev server, or interactive prompt that ran until a timeout. Fix: the non-interactive flag in the script, and a rule naming it.

Size it in minutes per session and sessions affected.

## 5. Validation

How a change gets checked before the agent says it is done, and how often that claim held.

Where to look: the tail of the final assistant message in each digest, the ask that follows it, the commands run before it, and on the tracker the first CI run of agent pull requests.

- **Done without proof**: a completion claim with no check run after the last edit. Fix: a stop hook or closing command that runs the checks. A rule is the weakest version.
- **Done, then not**: the next ask reports a failure the agent could have seen. Find which check would have caught it and whether the repo has it.
- **CI catches what local did not**: first-push failures on lint, types, or format. Fix: the same check as a local command or hook.
- **The wrong check**: unit tests passed and the app was broken, a UI change never opened in a browser. Fix: a documented way to run and look at the real thing.
- **No check exists**: a class of bug that recurs with nothing guarding it. Propose the test or the lint rule.
- **Checks too slow to run**: agents skip what takes ten minutes. Give them a fast path.
- **Reviews repeat themselves**: the same reviewer comment on several pull requests. Fix: a lint rule or a rule line.

Size it in "done" claims that did not hold, and in review or CI rounds per pull request.

## 6. Skipped errors

Something went wrong in plain sight and the session moved on.

Where to look: failed calls in the session digests that were never run again, then `show` around them.

- A failing test or type error followed by unrelated work, or by a claim of success.
- A check disabled to get past it: a skipped test, `--no-verify`, a lint suppression, a loosened assertion.
- Warnings that recur in output and are never addressed: deprecations, peer dependency conflicts, a flaky test.
- A partial result presented as complete: 3 of 5 files changed, a TODO left in place of the hard part.
- A subagent's failure that its parent never surfaced.
- An error the agent worked around by another route, leaving the trap for the next session.

Each one is two findings: the defect itself, which goes in the report as a possible open bug, and the flow that let it pass.

## 7. The rules themselves

Read each line of the rules against the sessions and against the repo.

| Problem | Test | Fix |
| --- | --- | --- |
| Stale | It names a script, path, or tool that no longer exists or behaves differently | Correct or delete |
| No-op | Agents do it unprompted. No session shows the rule changing anything | Delete |
| Ignored | Sessions break it repeatedly | Enforce, or rewrite it as the positive target and move it where it is read |
| Duplicate | The same meaning in two files, or in a rule and a skill | Keep one |
| Contradiction | The rules say one thing and the scripts, CI, or another rules file say another | Make the environment the source of truth |
| A cache of the environment | It restates what one look at `package.json` or `--help` gives | Delete, unless the lookup is costly |
| Missing | A pattern from lenses 1 to 6 with no rule, script, or check behind it | Add at the right rung |
| Wrong place | Reference that only some tasks need, loaded always | Move it behind a pointer |
| Split by harness | `CLAUDE.md`, `AGENTS.md`, and editor rules drifting apart, so agents on different harnesses get different instructions | One source, the others pointing at it |
| Tooling that does not load | A skill, command, or hook the rules name is a broken link, sits only in a user-level folder, or fails to parse. Sessions show the developer explaining by hand what the skill would have done | Repair the link or vendor it into the repo (ask first when it changes git settings) |
| Tooling nobody calls | A project skill, command, or MCP server with no call in the window (`count --in calls`) | Remove it, or fix the description that fails to trigger it (ask first) |
| Written for one harness | A rule that suits one harness and costs another: a loop one model needs and another does without | Scope the rule to where it applies |

Report the always-loaded size before and after.

## 8. The flow around the agent

What happens before a session starts and after it ends. This lens needs the tracker. With git only, say what it could not see.

- **Intake**: issues an agent cannot start from. Missing reproduction, no acceptance criteria, no pointer to the code. Fix: an issue template or a triage step.
- **Triage**: issues that sit unlabelled, duplicates, questions that the docs answer.
- **Handoffs**: the same context retyped when work moves between sessions, agents, or people. Fix: a handoff note convention, or a plan file the next session reads.
- **Review load**: agent pull requests too large to review, several rounds for the same class of comment, long waits for a human.
- **Abandoned work**: closed, unmerged pull requests, and branches or worktrees nobody returned to. Read why each run was thrown away.
- **Missed chances to automate**: chores people do by hand on a schedule that an agent could run: dependency updates, release notes, issue triage, stale branch cleanup.
- **Across the team**: one person's rules or skills that would help everyone, and the same mistake made by different people's agents.

Size it in runs thrown away, review rounds, and days waiting.
