# skills

My agent skills for Claude Code, Codex, Cursor, and other agents that read `SKILL.md` files.

| Skill | What it does | Trigger |
| --- | --- | --- |
| [`challenge-feature`](skills/challenge-feature/SKILL.md) | Argues against a feature idea before any code is written. Checks whether existing features already cover the need, what the change would cost to build and maintain, and how much harder the app gets to learn. Ends with a build / build smaller / don't build verdict. | Manual only |

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

Run it when you have an idea but aren't sure it belongs in the app:

```
/challenge-feature add snooze to bookmarks
```

It starts from "don't build it", and the feature has to make its case:

1. Names the problem behind the idea. If that's unclear, it asks you one question and waits.
2. Searches the codebase for features that already solve the problem, and says what gap is left.
3. Lists the build cost: files and layers touched, data changes, new permissions, edge cases, tests, maintenance.
4. Lists the cost to users: new UI, new concepts to learn, and features that start to overlap.
5. Considers cheaper options: do nothing, extend an existing feature, build a smaller version.
6. Gives a verdict and stops. It writes no code until you ask.

In Claude Code, `disable-model-invocation: true` keeps the agent from running it on its own, so it never runs on ordinary tasks. Agents that ignore that field may pick it up when you ask whether to build something. To keep it manual there too, name it explicitly.

## Adding a skill

1. Create `skills/<name>/SKILL.md` with `name` and `description` frontmatter. `npx skills init skills/<name>` writes a starter file.
2. Add a row to the table above.
3. Test it locally by symlinking it into your skills directory:

   ```bash
   ln -s "$PWD/skills/<name>" ~/.claude/skills/<name>
   ```
