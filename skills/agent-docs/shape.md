# Target shape

The shape this skill builds, and the rule for which file each rule lands in. The wording of every line is the business of `writing-for-agents`; this file only decides placement.

## Where a rule goes

Give each inventory row exactly one destination. Test them in this order and take the first that fits:

| Destination | When | Write it as |
| --- | --- | --- |
| `delete` | Code, config, a hook, a lint rule, a test, or a CI job already enforces it; it describes a file, command, or behavior that no longer exists; or another destination already holds it. | Nothing. The reason column names the enforcer (`.husky/pre-push`, `eslint.config.js` rule, `test.yml` job), the evidence it is stale, or the row and file that keep it. Open the enforcer and confirm before writing the reason. |
| `root` | Every task needs it, including a one-line docs fix: branch and commit rules, how to prove and report work, what never to do anywhere. | One line in Hard rules. |
| `folder <path>/AGENTS.md` | Missing it while editing that folder breaks something (the build, stored data, a deploy, another app), and an agent editing there could miss the topic doc. | One line with its reason. |
| `doc <docs folder>/<topic>.md` | Everything else: rules that only tasks of one kind need. | Under the heading for its topic, beside related rules. |

A row may be split (`12a`, `12b`) when one paragraph holds rules with different destinations. A rule that sits in the root and already in a doc maps to that doc.

**Long material every task needs**, such as a numbered task workflow of many steps, is split. The root keeps one hard rule per step that every task must not miss, plus a line naming the doc to load before the first edit ("Load workflow.md and validation.md before the first edit"); the steps' detail moves to that doc. When the root is still over the cap, the hard rules are too detailed: move each rule's how-to into its doc and keep the what in the root. When one rule per step still does not fit, keep the steps whose skipping is costly and goes unnoticed, and fold the rest into the single line that loads the workflow doc, naming it the definition of done.

Files a tool writes (a framework's generated `AGENTS.md`, for example) keep their rows as `folder <that path>` and stay untouched. The `CLAUDE.md` import beside one is the repository's own file, so it gets one like any other `AGENTS.md`.

## Root `AGENTS.md`

The map. About 60 lines and 5 KB, in this order. Both are targets, not hard caps: the budget is the hard limit, and it only stops growth. Go over them only for hard rules that pass the `root` test, and name the overage in the pull request.

1. **Title and what the project is**, 1 or 2 sentences. Say where humans start and that agents load the docs folder on demand.
2. **Layout**: one line per app, package, or top-level folder that work happens in, saying what it is and anything about it that crosses folders.
3. **How tasks run**: one line, such as "Run tasks as `pnpm run <task>` from the root". The scripts themselves stay in `package.json`.
4. **Hard rules**: the `root` rows.
5. **Load on demand**: one line per topic doc, worded as the situation that needs it, leading with its distinctive word, then an arrow and the link. A line may name a second, human doc to read after it.

A trimmed example of the shape:

```markdown
# TabLodge

A local first tab session and bookmark manager: four apps in a pnpm workspace sharing one library format. Humans start at [docs/README.md](docs/README.md); agents load [docs/agents/](docs/agents/) on demand below.

## Layout

- `apps/extension`: Chrome and Firefox extension. Its `src/shared` is also imported by the server and the Android app
- `apps/server`: Self hosted sync server
- `docs/`: All Markdown except the `AGENTS.md` files. `docs/agents/` is for you; each app also has a short `AGENTS.md`

Run tasks as `vp run <task>` from the root; scripts in the root `package.json` forward to the right app.

## Hard rules

- Never commit on or push to `main`; work on a `<type>/<short-topic>` branch and open a pull request.
- Report only what you ran. Say what you could not run or check.

## Load on demand

- Committing, pushing, opening or watching a pull request, hooks → [workflow.md](docs/agents/workflow.md)
- UI, styling, accessibility → [ui.md](docs/agents/ui.md)
- Sync server (`apps/server`) → [server.md](docs/agents/server.md)
- Editing docs; editing this file → [documentation.md](docs/agents/documentation.md)
```

## Topic docs

- One folder for all of them. Keep the repository's existing one (`docs/agents/`, `.agents/docs/`, ...); create `docs/agents/` when there is none.
- One topic per file, named for the situation (`workflow.md`, `ui.md`, `server.md`), each reached by one root pointer. A doc whose sections answer different triggers is two docs.
- First line under the title: what the doc covers, in one sentence. Then the rules, grouped under headings that a link can target.
- An existing doc that is already one topic stays where it is. Fix its pointer instead of rewriting it.

## Per-folder `AGENTS.md`

The harness loads it when an agent works in that folder, so it holds only what breaks something when missed. Under about 15 lines:

```markdown
# Sync server

Load [server.md](../../docs/agents/server.md) before editing here.

- After changing `src/`, run `pnpm run cf:bundle` and commit `cloudflare-deploy/worker.js`. The deploy button copies that file, not the source.
- Never remove the Durable Object `migrations` entry. It deletes the stored library.
```

A folder with no such rule gets no `AGENTS.md`; its topic doc is enough.

When the file is over 15 lines and every rule breaks something when missed, keep them all; the cap is a target. First make each rule one line, then move the rules that guard one subfolder into an `AGENTS.md` there, next to the code they protect, and list any rule a test or check could enforce as a proposal for the user.

## `CLAUDE.md`

Claude Code reads `CLAUDE.md`, other agents read `AGENTS.md`. When the repository is worked in Claude Code (a `CLAUDE.md` exists, or the user says so), every `AGENTS.md` gets a `CLAUDE.md` beside it holding the import line `@AGENTS.md` and nothing else, so the two never drift. Claude-only instructions, if any, follow the import and count as always loaded.

## The maintenance section

Without written rules the shape erodes. Put this section, adapted to the repository's paths and script names, into the topic doc for editing documentation (create `<docs folder>/documentation.md` when none exists), and give it a root pointer such as "Editing docs; editing `AGENTS.md` → documentation.md":

```markdown
## Agent docs

`AGENTS.md` is a map, not a manual. It holds the layout, the hard rules, and one pointer per doc, each saying when to load it. Everything else lives in `docs/agents/`.

- **Add a rule** to the doc whose pointer matches the situation, next to related rules. Delete a rule that code, config, or a script already enforces.
- **Add a doc** when a topic applies to some tasks only, and give it one line under Load on demand. Word the trigger as the situation, leading with the distinctive word, one trigger per branch.
- **Keep `AGENTS.md` under about 60 lines.** A rule every task needs stays; anything else moves to a doc.
- **Per-folder `AGENTS.md`** holds the few rules that break something when missed, each with its reason, and points to its doc for the rest. Under 15 lines.
- **The size budget.** `scripts/agent-context-budget.json` records the bytes of the `AGENTS.md` files and `docs/agents/`. After editing any of them run `node scripts/agent-context.mjs --write` and commit the result. CI fails a pull request whose budget is above the base branch's unless it has the `agent-context-increase` label. Cut text before asking for the label.
- Write or edit these files with the `writing-for-agents` skill loaded.
```

When the repository already has a doc on writing rules for agents, merge these lines into it instead of adding a second place.
