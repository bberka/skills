# skills

My agent skills for Claude Code, Codex, Cursor, and other agents that read `SKILL.md` files.

| Skill | What it does | Trigger |
| --- | --- | --- |
| [`challenge-feature`](skills/challenge-feature/SKILL.md) | Argues against a feature idea before any code is written. Checks whether existing features already cover the need, what the change would cost to build and maintain, and how much harder the app gets to learn. Ends with a build / build smaller / don't build verdict. | Asking to challenge an idea, or `/challenge-feature` |
| [`challenge-feature-panel`](skills/challenge-feature-panel/SKILL.md) | The same question, asked of a panel of subagents: engineer, UX designer, everyday user, product owner, and advocate. Each reviews the idea separately, and the main agent weighs their reports into one verdict. | Asking to challenge an idea, or `/challenge-feature` |

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

## Adding a skill

1. Create `skills/<name>/SKILL.md` with `name` and `description` frontmatter. `npx skills init skills/<name>` writes a starter file.
2. Add a row to the table above.
3. Test it locally by symlinking it into your skills directory:

   ```bash
   ln -s "$PWD/skills/<name>" ~/.claude/skills/<name>
   ```
