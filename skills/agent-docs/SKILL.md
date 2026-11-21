---
name: agent-docs
description: "Restructures a repository's agent instructions into a short always-loaded map plus docs loaded on demand, and adds a CI size budget so they cannot quietly grow back. Inventories every rule in the root and per-folder AGENTS.md and CLAUDE.md files and the docs they point to, gives each rule one destination (a root hard rule, a topic doc, a per-folder AGENTS.md, or deletion with a reason), rewrites the files, extends the repository's existing budget or installs one, and checks that every pointer and command resolves. Use when the user asks to shrink, split, restructure, or slim down AGENTS.md or CLAUDE.md, says the agent instructions are too long or load too much context, or wants a size budget or CI check for them. Don't use to add a single rule, or to find what to change from past sessions (agent-workflow-audit does that)."
argument-hint: "[scope, e.g. budget only, plan only, root AGENTS.md only]"
---

# Agent docs

Scope: $ARGUMENTS

(If that line is empty or still shows a placeholder, take the scope from the user's message. With no scope given: restructure every agent instruction file, add or extend the budget, and land it the way the repository lands changes.)

Every session pays for the root `AGENTS.md` in full. Turn it into a map: what the project is, its layout, how tasks run, the hard rules every task needs, and one pointer per topic doc. Everything else moves to docs loaded on demand, and a budget check keeps the total from growing back. Load the `writing-for-agents` skill before writing any line; it governs the wording, and this skill decides only where each rule goes.

## Files in this skill

Paths are relative to the folder that holds this file. Read each file when its step says to.

| File | Read or run it when |
| --- | --- |
| [shape.md](shape.md) | Steps 2 and 3, always. Where a rule goes, the root and per-folder layouts with examples, and the maintenance section the repository gets. |
| [budget.md](budget.md) | Step 4, always. Finding an existing budget, installing the templates, extending an existing one, and what CI does on this pull request. |
| `scripts/inventory.mjs` | Steps 2 and 5. Writes the inventory skeleton and checks that every row has a destination. `--help` lists the flags. |
| `scripts/check_pointers.mjs` | Step 5. Checks links, `#heading` anchors, `@` imports, `run <script>` commands, paths, sizes, and orphan docs. |
| `templates/` | Step 4, when the repository has no budget: `agent-context.mjs`, `agent-context.yml`, `agent-context.test.mjs`. |

The scripts need Node 18 or later and git, and run from inside the target repository (or take `--repo <dir>`).

## Words used here

- **Rule**: one instruction or fact an agent is told, as one inventory row.
- **Map**: the root `AGENTS.md` after this skill.
- **Topic doc**: a file in the docs folder, reached by one pointer.
- **Docs folder**: the repository's existing folder of agent docs; `docs/agents/` when it has none.
- **Pointer**: a line under Load on demand: the situation, an arrow, the link.
- **Always-loaded bytes**: the root `AGENTS.md` plus whatever the root `CLAUDE.md` adds besides importing it. Measured at the base branch (before) and on your branch (after).
- **Base**: the branch the pull request will merge into.

## Ground rules

- **Every rule has one destination.** No rule disappears without a row saying where it went or why it was deleted.
- **Moving keeps meaning.** A rule says the same thing at its destination. Add no rule the repository did not have, apart from the maintenance section in shape.md.
- **A deletion names its proof.** "Enforced" means you opened the hook, lint rule, test, or job and saw it enforce the rule.
- **The repository's workflow binds you.** Its rules on branches, worktrees, commits, checks, and pull requests apply to this change too. They live in the files you are about to rewrite, so read them first.
- **The inventory stays out of the repository.** It goes in the scratch folder and the pull request body.

## Steps

### 1. Read the repository

- List the agent instruction files: `git ls-files --cached --others --exclude-standard | grep -E '(^|/)(AGENTS|CLAUDE)\.md$'`, minus installed skill folders (`.claude/`, `.agents/`) and vendored text. Note files a tool writes.
- Find the docs folder and every doc the instruction files point to.
- Find an existing budget, as budget.md describes.
- Note the repository's workflow for landing a change: default branch, branch naming, worktree use, setup command, commit style and authorship, required checks, pull request body format. Sources: the instruction files, `CONTRIBUTING.md`, `.github/pull_request_template.md`, hooks.
- Record the before numbers: lines and bytes of each instruction file at the base (`git show origin/<base>:AGENTS.md | wc -lc`), and the always-loaded bytes. When the user gave a session count, multiply.

Then set up the branch or worktree the way the repository does it, from the up-to-date base, and run every later step there, so the inventory and the before numbers read the same tree.

Done when you can list each file with its size, the docs folder, the budget state (none, or its script, JSON, workflow, and `package.json` scripts), and the landing workflow, and you are on the new branch.

### 2. Inventory every rule

Read shape.md. Then write the skeleton to the scratch folder:

```bash
node <this skill>/scripts/inventory.mjs --out <scratch>/inventory.md [docs/to/split.md ...]
```

It holds one row per list item, table row, paragraph, or code block of every `AGENTS.md` and `CLAUDE.md`, and one row for each Markdown doc they link to. Name a linked doc as an extra argument when you will split it or move parts of it, and it gets one row per unit instead; a doc kept whole takes its own path as destination. Read each source line the row names, and fill in the destination and, for `delete`, the reason. Split a row holding rules with different destinations into `12a`, `12b`.

Done when `node <this skill>/scripts/inventory.mjs --check <scratch>/inventory.md` reports every unit with a destination.

### 3. Write the new files

Following shape.md:

1. Write each topic doc that receives rows: put each of its rows under the right heading, beside the rules already there. Add the maintenance section.
2. Write the per-folder `AGENTS.md` files from their rows, and `CLAUDE.md` imports where shape.md says.
3. Write the root map last, so its pointers name docs that exist. One pointer per topic doc.

Done when every row's text lives at its destination, the root is within about 60 lines and 5 KB, each per-folder file is within about 15 lines, and every `CLAUDE.md` is an import.

### 4. Add or extend the budget

Read budget.md and follow its branch for the repository: extend the existing budget, or install the templates. Then write the budget with its write command.

Done when the budget covers the root, the per-folder files, and the docs folder; the plain check passes; any test file for it passes; and the growth check against the base either passes or fails only on keys you can name and explain.

### 5. Verify

Run, from the repository root:

```bash
node <this skill>/scripts/check_pointers.mjs --docs <docs folder>
node <this skill>/scripts/inventory.mjs --check <scratch>/inventory.md --repo .
```

- `check_pointers.mjs` must report 0 errors. Resolve each warning or say in the pull request why it stays (a build output path, a generated file).
- The inventory check now also confirms every destination file exists. Read each destination and confirm its rule is there.
- Run every command the new files name that the checker could not resolve, or confirm it in its `package.json`, `Makefile`, or `--help`.
- Run the budget check and its tests as CI will, including the growth check against the base.
- Compute the after numbers the same way as in step 1.

Done when both commands pass, the budget check passes, and you have before and after figures for each file group and the always-loaded bytes.

### 6. Land it

Follow the repository's workflow from step 1: commit in its style and authorship, run its pre-push checks, push, and open the pull request in its format. When the user said not to push, stop at a committed branch.

The pull request body carries:

- The before and after table: always-loaded bytes, root lines, each budget group, and the net change.
- The inventory summary (rows by destination, from `--check`) and the full inventory in a collapsed `<details>` block. When it is too long for the body, post it as the first comment.
- The deleted rows with their reasons, in the open, since a reviewer checks those first.
- The budget growth CI will report, and the request for the `agent-context-increase` label (budget.md).

Done when the pull request is open, or the branch is committed when pushing was not allowed.

### 7. Report

In the chat: the pull request link or branch, the before and after always-loaded bytes, rows by destination, warnings left with their reason, and anything only the user can do (the label, a required check to add).
