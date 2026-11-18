# Sources

Where the evidence lives and how to reach it. Check each class, use what answers, and put the rest in the reach table with the reason. Everything here is read-only.

## Agent sessions on this machine

`scripts/session_digest.py scan` reads these stores directly and matches their sessions to the repo, worktrees included. A store that is absent is reported and skipped.

| Harness | Store |
| --- | --- |
| Claude Code | `~/.claude/projects/<working directory>/*.jsonl`, subagents beside them |
| Codex | `~/.codex/sessions/` and `~/.codex/archived_sessions/`, indexed by a `state_*.sqlite` |
| OpenCode | `~/.local/share/opencode/` |
| Pi | `~/.pi/agent/sessions/<working directory>/*.jsonl` |
| T3 Code | `~/.t3/userdata/statev2.sqlite`. It runs the other harnesses, so the script counts each wrapped session once |

Other harnesses keep history too. These paths move between versions, so confirm a path exists and look at one record before trusting it.

| Harness | Where to look |
| --- | --- |
| Gemini CLI, Antigravity | `~/.gemini/` |
| Cursor | the app's `state.vscdb` under its user data folder, and `~/.cursor/` |
| Aider | `.aider.chat.history.md` and `.aider.input.history` in the repo |
| Cline, Roo, Continue | the extension's folder under the editor's `globalStorage` |
| Copilot CLI, Amp, Goose, Crush, and others | the tool's folder under `~/.config/`, `~/.local/share/`, or the home directory |
| Cloud agents (Claude Code on the web, Codex cloud, Copilot coding agent, Devin, Jules) | the vendor's session pages, and the pull requests they opened |

For a store the script does not read:

1. Probe one session's shape with a few lines of `jq`, `sqlite3 ... LIMIT 3`, or Python. Print keys and truncated values, never whole files.
2. Run `session_digest.py format`. It prints a small event format: one JSON line per ask, tool call, tool result, and usage record.
3. Write a throwaway converter in the scratch folder that emits that format, and pass its output to `scan --import <file>`. The script then digests those sessions with the rest. The asks must be what a person typed, with tool results and injected text left out. Give each session the working directory or git remote it ran in, since the scan keeps only sessions that match the repo.
4. Say in the report which stores came in through a converter.

Sessions run in a worktree or a container are stored under that path, not the repo's. The script handles this for the stores it reads. In a converter, match on the git remote where the store records it, then on the working directory.

## The harness's own thread tools

Some harnesses give the agent tools over their threads: list, search, and read, and sometimes the same on other machines or for other people. T3 Code has `t3_thread_list`, `t3_thread_search`, `t3_thread_read`, and `t3_environment_links` for linked machines. Look through your tool list for the equivalent, deferred tools included.

They reach what the disk may not: threads on linked or remote environments, cloud threads, a teammate's threads the harness shares with you, and threads whose transcript was cleaned up. Use them alongside the script:

- **Search** to check a candidate pattern in threads the scan cannot see (other machines, other people, an older window): search for the phrase with a small result limit and note how many threads match. Results can be large, so ask for a handful.
- **List** to see which projects, machines, and people have threads for this repo, and put that in the reach table.
- **Read** for an excerpt from a thread the script cannot open. Ask for a few items at a small character limit, never a whole thread.

The numbers still come from the script: it reads thousands of items for no tokens, and a thread read is paid for item by item.

## Team sessions

Local stores hold one person's sessions. Look for the team's in this order:

1. A shared store: the harness's thread tools where they list other people's or other machines' threads, a team workspace, or a server where agents run for everyone.
2. Cloud agent sessions tied to the repo, reachable through the vendor's CLI or the tracker.
3. Transcripts or agent logs committed to the repo or attached to pull requests.
4. The tracker, as a proxy: agent-authored pull requests, their reviews, and their CI runs show what teammates' agents got wrong even when the sessions are out of reach.

When only the proxy is reachable, say so, and put this in "needs a human": each teammate can run `session_digest.py scan` on their own machine and share `summary.md`. It holds numbers, command names, and session titles, so sharing is their choice. `prompts.md` holds what they typed and stays with them unless they offer it.

## The tracker

Find the host from `git remote -v`, then the tool that reaches it:

| Host | Tool |
| --- | --- |
| GitHub, GitHub Enterprise | `gh` |
| GitLab | `glab` |
| Gitea, Forgejo, Codeberg | `tea`, or the REST API |
| Bitbucket | the REST API with a token |
| Azure DevOps | `az repos`, `az boards`, `az pipelines` |
| Gerrit | `ssh <host> gerrit query`, or the REST API |
| SourceHut | `hut` |

Issue trackers outside the git host (Jira, Linear, YouTrack, Shortcut) are reached through an MCP tool or their CLI when one is connected. Discover by capability: look at the tools you have and at `--help`, and check the sign-in (`gh auth status`, `glab auth status`). A tool that is missing or signed out goes in the reach table with the command that would fix it.

What to pull, capped so the tracker costs less than the sessions did. Ask for the fields you need, not whole objects.

- **Pull requests** merged or closed in the window, 50 at most: author, whether an agent wrote it (bot author, co-author trailer, branch prefix, label), review comments, pushes after the first review, time from open to merge, failed CI runs. A closed, unmerged agent pull request is a whole run thrown away: read why.
- **Review comments** on agent-written pull requests. The same comment from a reviewer three times is a rule or a lint check waiting to be written.
- **Issues**, open and recently closed: how they are triaged and labelled, whether an issue gives an agent what it needs to start (a reproduction, acceptance criteria, the files involved), and which ones bounced back after an agent's fix.
- **CI** on agent branches: how often the first push fails and on which job. A job that fails first-push again and again is a check agents should run locally.
- **Boards, milestones, discussions**: how work reaches an agent, and where it waits.

## Written material

- Repo docs: `README`, `CONTRIBUTING`, `docs/`, architecture notes, runbooks. Note what contradicts the rules or the scripts.
- The wiki, when the host has one: usually a second git repo (`<repo>.wiki.git`) you can clone read-only.
- External docs the rules or the README link to (a docs site, a design doc, a spec). Open the ones agents were pointed at in sessions.
- Feature ideas and roadmaps, to see whether agents are given the context behind the work.

## The org

When your token reaches beyond the repo:

- Other repos' rules files. A rule every repo repeats belongs in one shared place, and a good rule in one repo may be missing here.
- A shared config repo (`.github` on GitHub, a group-level template project on GitLab), org-level agent instructions, shared skills or plugins, and reusable workflows.
- Org rulesets and required checks that shape what an agent's pull request has to pass.

A repo under a personal account has no org. Sample the owner's other repos the same way: rules worth sharing across them, and rules this repo lacks.

Read only, and sample: five repos tell you whether a pattern is org-wide. Changes outside this repo are proposals for a human.

## Git history, always there

`git log` in the window answers a lot with no tracker at all:

- Reverts, and commits that fix the commit before them ("fix lint", "fix types", "address review"): validation that ran too late.
- Agent trailers (`Co-Authored-By`, `Generated with`) and bot authors: which commits agents wrote.
- Churn on the rules files: who edits them, how often, and whether lines only ever get added.
- Branches and worktrees left behind: runs that were abandoned.
