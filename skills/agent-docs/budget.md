# Size budget

A committed JSON file records the bytes of the agent instructions, a script fails when the files and the file disagree, and a pull request check fails when the budget rises above the base branch's. Growth then shows up in a diff and needs a maintainer's label, instead of settling in unnoticed.

The budget must cover three groups: the root `AGENTS.md` (with root `CLAUDE.md`), the per-folder `AGENTS.md` and `CLAUDE.md` files, and the topic docs folder.

## Find an existing budget

Search before adding one:

```bash
git grep -il 'agent.context\|agents\.md.*bytes\|context.budget' -- scripts .github package.json '*.mjs' '*.ts' '*.js' '*.yml'
```

Look for a script that measures `AGENTS.md`, a JSON of sizes beside it, a workflow or CI script that runs it, and `package.json` scripts that call it. Skip hits that only mention the words. When any of them exists, extend it (below). When none does, install the templates.

## Install the templates

From this skill's `templates/` folder:

| Template | Goes to | Change |
| --- | --- | --- |
| `agent-context.mjs` | `scripts/agent-context.mjs` | `GROUPS`: the docs folder path and, if the repository's per-folder files live only under known folders, a narrower pattern such as `apps/*/AGENTS.md`. `EXCLUDE`: installed skills, vendored text, and any file a tool writes. |
| `agent-context.yml` | `.github/workflows/agent-context.yml` | Match the runner label and the `actions/checkout` version the repository's other workflows pin. |
| `agent-context.test.mjs` | `scripts/agent-context.test.mjs` | Only when the repository runs `node --test` files in CI; add it to that command. |

Then:

1. Add `package.json` scripts in the repository's naming style when it routes tasks through them, such as `"agent-context:check": "node scripts/agent-context.mjs"` and `"agent-context:write": "node scripts/agent-context.mjs --write"`.
2. Run `node scripts/agent-context.mjs --write`, then `node scripts/agent-context.mjs` (passes).
3. Create the label if it is missing. `gh label list --search` matches loosely, so check the exact name: `gh api 'repos/{owner}/{repo}/labels/agent-context-increase' --silent` fails when it does not exist. Then `gh label create agent-context-increase --description "Accepts growth of the agent instructions"`. Label creation is outward-facing: do it when the user has allowed pushing to the remote, otherwise list it for the user.

The script keys the budget by group, so a new doc raises its group's total and counts as growth. A group the base budget does not have yet is skipped, since there is nothing to grow from.

The script reads the file list from `git ls-files --cached --others --exclude-standard`: untracked new files count, ignored copies (nested worktrees, build output) do not, and a file deleted from disk but still in the index is skipped.

## Extend an existing budget

Keep what the repository already relies on: the script and budget file names, the key format (per file or per group), the flag syntax (`--base=REF` or `--base REF`), the `package.json` script names, and the workflow file, workflow name, and job name. A required status check is bound to the job name; renaming it blocks every pull request.

Change four things:

1. **Coverage.** Make the measurement include the topic docs folder, and root and per-folder `CLAUDE.md` when it skips them. Keep its existing skip list (third-party skill folders, generated files).
2. **File list.** When it lists files with plain `git ls-files`, add `--cached --others --exclude-standard` and skip paths missing on disk. Otherwise a new doc is not measured until it is staged, and a file deleted but still in the index crashes the size lookup.
3. **New files count as growth.** Check how the growth comparison treats a key missing from the base budget. A per-file budget that skips missing keys lets a new doc in unseen. Fix it so a file that did not exist at the base counts as growing from 0 (`git cat-file -e <ref>:<file>` fails for it), while a file that existed but was not measured before is newly measured, not growth. A per-group budget already counts a new file in its group's total.
4. **Tests.** Extend its test file with a case for each change: a docs-folder file is measured, a new file at a ref where it does not exist is growth, an existing file newly measured is not. Run the test command the repository uses for it.

Then rewrite the budget with the repository's own write command and check that the plain check passes.

## The restructure pull request

Moving rules out of the root shrinks the root and grows the groups that receive them. Expect the growth check to fail on the receiving keys. That is the label's job:

- Report each key's change and the net change, base to head, in the pull request body. The growth check lists what grew. For the rest, measure the base from git rather than its budget file, which lacks any group or file the budget did not cover yet: `git ls-tree -r -l origin/<base> -- AGENTS.md CLAUDE.md <docs folder>` prints each file's size at the base (fourth column), and `git ls-tree -r -l origin/<base> | grep -E '/(AGENTS|CLAUDE)\.md$'` the per-folder files. Sum them per key and compare with the new budget.
- **Commit order.** The budget must match the files in every commit, and a hook that runs the check reads the working tree, not the commit. So finish one change before starting the next: edit, run the write command, stage the files and the budget together, commit, and only then edit for the next commit. With edits for several commits already in the tree, the hook passes while a commit in the middle mismatches; commit them as one or rebuild them in order.
- Ask the maintainer for the `agent-context-increase` label in the body. Add it yourself only when the user tells you to.
- Keep the net change negative. Deleted rows should outweigh what the docs gained; when they do not, look again at `delete` candidates and duplicated text before asking for the label.
