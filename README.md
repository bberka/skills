# skills

My agent skills for Claude Code, Codex, Cursor, and other agents that read `SKILL.md` files.

| Skill | What it does | Trigger |
| --- | --- | --- |
| [`challenge-feature`](skills/challenge-feature/SKILL.md) | Argues against a feature idea before any code is written. Checks whether existing features already cover the need, what the change would cost to build and maintain, and how much harder the app gets to learn. Ends with a build / build smaller / don't build verdict. | Asking to challenge an idea, or `/challenge-feature` |
| [`challenge-feature-panel`](skills/challenge-feature-panel/SKILL.md) | The same question, asked of a panel of subagents: engineer, UX designer, everyday user, product owner, and advocate. Each reviews the idea separately, and the main agent weighs their reports into one verdict. | Asking to challenge an idea, or `/challenge-feature` |
| [`usability-audit`](skills/usability-audit/SKILL.md) | Opens the running app on every supported device, walks the main tasks, and judges the screenshots as a hurried first-time user would. Also checks what screen reader and keyboard users get. Writes a ranked report of what would confuse or stop people, with a fix for each. Covers app screens, landing pages, and pricing pages. Changes no code. | Asking for a usability, UX, or accessibility audit, or `/usability-audit` |
| [`ci-optimize`](skills/ci-optimize/SKILL.md) | Measures what a pull request waits on from real run history, reads the merge rules, applies the speedups that leave every check meaning the same thing, and asks before anything that changes what is checked or how the app is built. Proves the gain with a before and after table from real runs. Sets CI up when a project has none. GitHub Actions and GitLab CI. | Asking to speed up, optimize, or set up CI, or `/ci-optimize` |
| [`agent-workflow-audit`](skills/agent-workflow-audit/SKILL.md) | Reads a repo's past agent sessions, its agent rules and docs, and whatever tracker history is reachable, and finds where agents lose time, tokens, and your attention: asks you keep repeating, mistakes they keep making, loud commands, weak validation, skipped errors. Updates the rules and docs, proposes hooks, scripts, and skills, and lists what only a human can change. Any agent CLI, any git host. | Asking to audit or optimize your agent workflow, sessions, or token use, or `/agent-workflow-audit` |
| [`agent-docs`](skills/agent-docs/SKILL.md) | Turns a long `AGENTS.md` into a short map (what the project is, layout, how tasks run, hard rules, and a load-on-demand list) plus topic docs read only when a task needs them. Gives every existing rule one destination, or deletes it with the reason, so nothing is dropped silently. Adds a CI size budget, or extends the one you have, so the instructions cannot grow back unnoticed. | Asking to shrink, split, or restructure `AGENTS.md` or `CLAUDE.md`, or `/agent-docs` |

The unslop skills live in their own repo: [bberka/unslop-skills](https://github.com/bberka/unslop-skills).

## Install

With the [skills CLI](https://skills.sh):

```bash
# every skill in this repo
npx skills add bberka/skills

# one skill
npx skills add bberka/skills --skill challenge-feature

# user-level (all projects) instead of the current project
npx skills add bberka/skills -g

# see what's available without installing
npx skills add bberka/skills --list
```

By hand: copy a folder from `skills/` into your agent's skills directory.

| Agent | User-level | Project-level |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Other agents | `~/.agents/skills/` | `.agents/skills/` |

```bash
git clone https://github.com/bberka/skills.git
cp -r skills/skills/challenge-feature ~/.claude/skills/
```

To update, run `npx skills update`, or `git pull` and copy again.

## Using them

### challenge-feature

Run it when you have an idea but aren't sure it belongs in the app. Ask in plain words or name it:

```
challenge the snooze idea before we build it
is a snooze feature even worth adding?
/challenge-feature add snooze to bookmarks
```

It only starts when you ask for a challenge. A plain "add snooze" goes straight to the work.

It starts from "don't build it", and the feature has to make its case:

1. Names the problem behind the idea. If that's unclear, it asks you one question and waits.
2. Searches the codebase for features that already solve the problem, and says what gap is left.
3. Lists the build cost: files and layers touched, data changes, new permissions, edge cases, tests, maintenance.
4. Lists the cost to users: new UI, new concepts to learn, and features that start to overlap.
5. Considers cheaper options: do nothing, extend an existing feature, build a smaller version.
6. Gives a verdict and stops. It writes no code until you ask.

### challenge-feature-panel

For bigger decisions, where one reviewer might miss an angle:

```
/challenge-feature-panel add snooze to bookmarks
```

1. Frames the problem and briefs the panel with facts and file pointers only, so its own opinion doesn't shape theirs.
2. Spawns one read-only subagent per role, in parallel. The roles are in [roles.md](skills/challenge-feature-panel/roles.md):
   - **engineer:** build cost, edge cases, upkeep
   - **ux:** where the feature lives, clutter, overlap with existing features
   - **user:** a non-technical user: would they find it, use it, or get confused?
   - **product:** whether it fits the app's purpose, scope creep, cheaper options
   - **advocate:** the strongest honest case for building it. Its vote isn't counted.
3. Weighs evidence rather than counting votes, and checks the code itself when panelists disagree on a fact.
4. Gives one verdict with a vote table, the settled disputes, and a recommendation, then stops.

To pick other roles, name them: `/challenge-feature-panel add snooze roles: engineer,user,accessibility`. If a role isn't in roles.md, the main agent writes a brief for it.

It spawns five agents, so use `challenge-feature` for quick checks. Agents without subagent support play the roles one at a time in a single context.

### When the panel runs

The panel never starts on its own. In Claude Code, `disable-model-invocation: true` keeps the agent from picking it. It runs in two cases:

- You name it: `/challenge-feature-panel ...`
- You ask `challenge-feature` for subagents, a panel, or several perspectives ("challenge the snooze idea with subagents"). `challenge-feature` then reads the panel's `SKILL.md` from the sibling folder, so install both together.

Agents that ignore `disable-model-invocation` may pick the panel on their own. Name the skill you want to be sure.

### usability-audit

Run it when the app works and you want to know whether a person can use it. Agents write UI code that works and are poor judges of whether it's usable, so this skill looks at the running app and not at the code.

```
/usability-audit
/usability-audit onboarding flow, android only
is the pricing page clear enough?
would a non-technical person get through signup on a phone?
```

It loads on its own for requests like the last two.

It audits only what you ask for:

| You say | It audits |
| --- | --- |
| nothing specific | the screens of the three to five main tasks |
| "just the account panel", "only the landing page" | those screens, with their states and dialogs |
| "the signup flow" | every screen from the flow's start to its end |
| "the changed UI files", "the diff", "this branch", "PR 42" | only the screens the git changes touch, and only what the change added or made worse. Older problems on those screens get a short list at the end. |
| "accessibility only", "mobile only", "android only" | only those checks or devices |

With three screens or fewer in scope it answers in the chat. With more it writes the report file. A full audit runs like this:

1. Works out what the product is, the three to five things people come to do, and which platforms it supports. It asks you when the project doesn't say, and for a test account when screens sit behind a login.
2. Starts the app (dev server, Android emulator, iOS simulator, desktop build) and walks each task from a cold start, taking a screenshot at every step, plus the empty, error, and keyboard-open states.
3. Shows the screenshots to a fresh subagent that knows nothing about the product and asks what each screen is for and where it would tap. Wrong answers become the top findings.
4. Checks every screen against the rules for [app screens](skills/usability-audit/rules-app.md) and, when they're in scope, [landing and pricing pages](skills/usability-audit/rules-marketing.md).
5. Measures what an image can't show reliably (tap target sizes, text sizes, contrast, clipped text) with [measure.js](skills/usability-audit/scripts/measure.js).
6. Checks [screen reader and keyboard use](skills/usability-audit/rules-accessibility.md): a second fresh subagent gets only the accessibility tree, as someone who hears the page, and the main tasks are walked with the keyboard alone.
7. Compares the same screen across devices.
8. Writes `usability-audit/<date>/report.md` with the screenshots: a verdict, a table of tasks, ranked findings with a fix for each, and quick wins. Then it stops.

On landing pages it checks that a stranger understands the product in five seconds and sees one clear next step. On pricing pages it checks that the plan you want people to buy is the obvious pick and that the price holds no surprises. It recommends clarity, and reports fake urgency, hidden costs, and similar tricks as problems to remove. Its landing and pricing advice is a set of hypotheses to A/B test, since it can't measure conversion.

It needs a way to drive a browser or device: a browser tool in your agent, or Playwright, `adb`, and Xcode from the shell. For the web it ships two Playwright scripts, [shots.mjs](skills/usability-audit/scripts/shots.mjs) and [tabwalk.mjs](skills/usability-audit/scripts/tabwalk.mjs). A platform it can't launch is listed as not audited. The accessibility pass is a usability check, not a WCAG conformance audit.

The rules draw on Nielsen's [ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/), Steve Krug's *Don't Make Me Think*, [WCAG 2.2](https://www.w3.org/TR/WCAG22/), the [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/), Apple's and Google's platform guidelines, the [Laws of UX](https://lawsofux.com/), and Baymard Institute's research on forms and checkout.

### ci-optimize

Run it when CI is slow, costs too much, or doesn't exist yet.

```
/ci-optimize
/ci-optimize the test workflow, report only
why do our pull request checks take ten minutes?
set up CI for this project
```

It works from measurements, since most changes that look like speedups move nothing a developer waits on:

1. Finds the provider, the workflows that run on a pull request, and the commands they run.
2. Measures the baseline with [ci_timing.py](skills/ci-optimize/scripts/ci_timing.py): the wait from push to the last blocking check, runner minutes, each job's median time, how often each job finished last, and the step times of the slowest jobs. The same script reads the merge rules (GitHub rulesets and branch protection, GitLab merge settings) to learn which checks block a merge.
3. Reads the comments and git history of the CI config, so a deliberately slow step isn't "fixed".
4. Lists candidate changes from [levers.md](skills/ci-optimize/levers.md), each sized from the measured step times, starting with the slowest chain that blocks the merge.
5. Applies the safe ones. Asks first, in one question, about anything that changes what is checked or when, changes the app or its build, is a large refactor, touches merge rules, or costs money. Each of those comes with a guardrail, such as the full suite still running after merge.
6. Makes the changes on a branch, one per commit, and confirms every required check still reports.
7. Pushes when you agree, runs CI a few times, and compares before and after with the same script. A change that shows no gain is reverted.
8. Reports the before and after table, what was kept, what was dropped, and the decisions left for you.

| Kind of change | Examples | What it does |
| --- | --- | --- |
| Safe | parallel jobs, dependency and tool caches, cancelling superseded runs, shallow checkout, sharding, shards filled by recorded test time ([split_by_time.py](skills/ci-optimize/scripts/split_by_time.py)) | Applies, then keeps only what measured faster |
| Needs a yes | running only the tests a diff can reach, swapping `tsc` or ESLint for a faster tool, trimming the pull request matrix, moving slow suites to after merge, larger runners, any ruleset change | Asks once, with the measured saving and the cost of each |

It needs `python3` and a signed-in `gh` for GitHub, or a `GITLAB_TOKEN` (or `glab`) for private GitLab projects. Without run history it can only review the config, and says so. On other CI providers the lever list still applies, and the timing script does not.

Its lever list draws on the GitHub Actions and GitLab CI documentation, [GitLab CI Optimization: 15+ Tips for Faster Pipelines](https://dev.to/zenika/gitlab-ci-optimization-15-tips-for-faster-pipelines-55al), and [How to Speed Up a Slow CI Pipeline](https://www.devopsness.com/blog/speed-up-ci-pipeline).

### agent-workflow-audit

Run it when agents in a repo feel slow or expensive, or when you notice you keep typing the same instructions.

```
/agent-workflow-audit
/agent-workflow-audit last 14 days, report only
/agent-workflow-audit tokens only
audit how my agents work in this repo and fix the rules
```

It works from what already happened, and every finding comes with the sessions it was seen in and a size:

1. Maps what it can reach: agent sessions on this machine, team sessions, the tracker (pull requests, reviews, issues, CI), docs and wiki, the org, and git history. Whatever it could not open is listed in the report with the reason.
2. Digests the sessions with [session_digest.py](skills/agent-workflow-audit/scripts/session_digest.py), which reads the Claude Code, Codex, OpenCode, Pi, and T3 Code stores directly, worktree sessions included. It writes the numbers, every ask you typed, and one short digest per session, so the agent never reads a raw transcript. Any other agent CLI comes in through a small converter and `scan --import`.
3. Reads the agent rules and docs, measures what every session pays to load them, and checks the commands and paths they name.
4. Looks through eight lenses ([lenses.md](skills/agent-workflow-audit/lenses.md)): repeated asks, corrections and repeated mistakes, token sinks, time sinks, validation, skipped errors, the rules themselves, and the flow around the agent.
5. Confirms each finding against the transcript, counts it, sizes it, and names the root cause. Fewer than three sessions is an anecdote and stays out.
6. Picks the strongest fix that works: remove the cause, then enforce with a hook or check, then automate with a script or skill, then a rule line, then a doc.
7. Applies what is safe on a local branch, asks once about the rest, and reports.

| Set | Examples | What it does |
| --- | --- | --- |
| Apply now | edits to `AGENTS.md`, `CLAUDE.md`, and docs, pruning stale or duplicate rules, project scripts and commands that run only when called | Applies on a branch, one commit per finding |
| Ask first | hooks, CI checks, lint rules, permission lists, default models, user-level files, anything pushed or posted | Asks once, with the evidence and the saving for each |
| Needs a human | org and billing settings, access it was not given, team habits, your own prompting habits | Lists who has to do what, and why an agent cannot |

It needs `python3`. The tracker lens uses whichever tool reaches your host (`gh`, `glab`, `tea`, `az`, an MCP tool) and falls back to git history when none is signed in. Nothing is pushed, opened, or posted unless you ask.

The report ends with baseline numbers. After the changes have been in use for a while, scan the two windows and run `session_digest.py compare` to see what moved.

### agent-docs

Run it when the root `AGENTS.md` has grown into a manual that every session pays for, or after `agent-workflow-audit` says the rules cost too much.

```
/agent-docs
/agent-docs budget only
our AGENTS.md is 250 lines, split it into docs loaded on demand
```

1. Reads the instruction files, the docs they point to, any existing size budget, and how the repo lands changes (branches, worktrees, commits, pull requests).
2. Writes an inventory to a scratch file with [inventory.mjs](skills/agent-docs/scripts/inventory.mjs): one row per rule, each given one destination. A root hard rule, a topic doc, a per-folder `AGENTS.md`, or deleted, with what enforces it or why it is stale. The script fails while any row has none.
3. Rewrites the files to the shape in [shape.md](skills/agent-docs/shape.md): the root map at about 60 lines, per-folder files under 15 lines for the rules that break something when missed, `CLAUDE.md` files as `@AGENTS.md` imports, and a section that tells future agents how to keep the shape.
4. Adds the budget from [templates/](skills/agent-docs/templates/): a dependency-free Node script, the committed JSON of sizes, and a GitHub Actions check that fails a pull request whose instructions grew, unless it has the `agent-context-increase` label. An existing budget is extended to cover the docs folder instead of getting a second one.
5. Checks with [check_pointers.mjs](skills/agent-docs/scripts/check_pointers.mjs) that every link, heading anchor, import, and named script exists, and that every doc has a pointer.
6. Lands it the way the repo does, with the before and after always-loaded bytes and the inventory in the pull request.

It writes the text with the `writing-for-agents` skill loaded. It needs Node 18 or later and git; the workflow template is for GitHub Actions.

## Adding a skill

1. Create `skills/<name>/SKILL.md` with `name` and `description` frontmatter. `npx skills init skills/<name>` writes a starter file.
2. Add a row to the table above.
3. Test it locally by symlinking it into your skills directory:

   ```bash
   ln -s "$PWD/skills/<name>" ~/.claude/skills/<name>
   ```
