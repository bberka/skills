# skills

My agent skills for Claude Code, Codex, Cursor, and other agents that read `SKILL.md` files.

| Skill | What it does | Trigger |
| --- | --- | --- |
| [`challenge-feature`](skills/challenge-feature/SKILL.md) | Argues against a feature idea before any code is written. Checks whether existing features already cover the need, what the change would cost to build and maintain, and how much harder the app gets to learn. Ends with a build / build smaller / don't build verdict. | Asking to challenge an idea, or `/challenge-feature` |
| [`challenge-feature-panel`](skills/challenge-feature-panel/SKILL.md) | The same question, asked of a panel of subagents: engineer, UX designer, everyday user, product owner, and advocate. Each reviews the idea separately, and the main agent weighs their reports into one verdict. | Asking to challenge an idea, or `/challenge-feature` |
| [`usability-audit`](skills/usability-audit/SKILL.md) | Opens the running app on every supported device, walks the main tasks, and judges the screenshots as a hurried first-time user would. Also checks what screen reader and keyboard users get. Writes a ranked report of what would confuse or stop people, with a fix for each. Covers app screens, landing pages, and pricing pages. Changes no code. | Asking for a usability, UX, or accessibility audit, or `/usability-audit` |

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

## Adding a skill

1. Create `skills/<name>/SKILL.md` with `name` and `description` frontmatter. `npx skills init skills/<name>` writes a starter file.
2. Add a row to the table above.
3. Test it locally by symlinking it into your skills directory:

   ```bash
   ln -s "$PWD/skills/<name>" ~/.claude/skills/<name>
   ```
