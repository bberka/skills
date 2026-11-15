# GitHub Actions

How the levers in [levers.md](levers.md) are written for GitHub Actions, and the traps specific to it. Check action versions and inputs against each action's README before writing them: majors change often, and the project may pin actions by commit SHA, in which case keep that style.

## Merge rules and required checks

`scripts/ci_timing.py rules` reads both rulesets and classic branch protection. What the output means for your changes:

- **A required check is matched by name.** The name is the job's `name:` (or its key when it has none). A matrix job reports as `name (value, value)`. A job inside a reusable workflow reports as `caller job / inner job`. Renaming a job, changing a matrix value, or moving a job into a reusable workflow changes the name and leaves the old required check pending forever.
- **A skipped job passes; a workflow that never started does not report.** A job skipped by a job-level `if:` counts as passed for a required check. A workflow skipped by `paths:`, `paths-ignore:`, or `branches:` on its trigger reports nothing, and a required check from it stays pending, so the pull request cannot merge. Path-filter a workflow at the trigger only when none of its jobs is required. Otherwise let the workflow start and decide inside it: a first job that detects changed paths, and the other jobs with an `if:` on its outputs.
- **An aggregate job is the stable gate.** One final job that `needs:` every other job, runs with `if: always()`, and fails unless each needed result is `success` or `skipped`. Require only that job in the ruleset. Jobs can then be added, split, sharded, and renamed without touching merge rules. If the project lacks one and has required checks, proposing it is an **Ask**: the ruleset must change with it.
- **"Branch must be up to date" (strict)** forces a rebase and a full re-run whenever the base moves. On a busy repository this is a large hidden wait. A merge queue removes it. Both are merge-rule changes: **Ask**.
- **A merge queue needs the `merge_group` trigger** on every workflow that owns a required check. Without it, the queue waits forever. Jobs that only make sense on pull requests need an `if:` that still lets them report in the queue.
- **Required reviews and other rules** don't affect CI time. Leave them alone.

Reading the rules needs no admin rights on a public repository. On a private one, a token without access returns an error, which the script prints: ask the user for the rules then.

## Triggers and cancellation

```yaml
on:
  pull_request:
  push:
    branches: [main]        # not every branch: a pull request push would run twice

concurrency:
  group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}
  cancel-in-progress: true
```

`github.head_ref` is set only on pull requests, so pull request pushes cancel their older runs while each default-branch push gets its own group and runs to the end. Give release and deploy workflows their own group with `cancel-in-progress: false`.

`pull_request` defaults to `opened`, `synchronize`, and `reopened`. Extra `types:` such as `edited` or `labeled` start runs with no new code: keep them only on the small job that needs them.

## Jobs

- Jobs run in parallel unless `needs:` orders them. Each job costs 10 to 25s of startup before its first step, plus checkout and setup.
- Billing rounds every job up to a whole minute. On private repositories Windows minutes cost about twice Linux and macOS about ten times: confirm the current rates in GitHub's billing docs before quoting a cost.
- Set `timeout-minutes` on every job. The default is six hours, and a hung job holds the gate until it ends.
- Matrix shards of one suite: `fail-fast: true`. Diagnostic matrices (OS, version): `fail-fast: false`.
- Start with `permissions:` at the least the job needs. Keep whatever least-privilege setup the project already has.
- Shared setup goes in a composite action under `.github/actions/`, or a reusable workflow. A reusable workflow changes check names (see above).

Parallel steps inside one job, when setup dominates:

```yaml
- run: |
    pnpm lint & lint=$!
    pnpm typecheck & types=$!
    wait $lint; a=$?
    wait $types; b=$?
    exit $((a | b))
```

Output interleaves. For more than two commands, write each one's output to a file and print the files of the ones that failed.

## Caching

- The `setup-*` actions (node, python, go, java, dotnet, and others) have a built-in dependency cache switched on by one input. Prefer it to a hand-written cache step: it keys on the lockfile and caches the package manager's store. Read the action's README for the input name and what it requires (some need a lockfile to exist).
- `actions/cache` for everything else. Key on what invalidates the content, with a prefix fallback:

  ```yaml
  - uses: actions/cache@<version>
    with:
      path: <tool cache dir>
      key: <tool>-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('<lockfile>', '<tool config>') }}
      restore-keys: <tool>-${{ runner.os }}-${{ runner.arch }}-
  ```

- **Scope.** A run can restore caches saved on its own branch, its base branch, and the default branch. A cache saved by a pull request is invisible to other pull requests. So the default branch must run the workflow and save the cache, or every pull request starts cold. If the workflow never runs on the default branch (pull-request-only trigger, or path filters that skip it), add a push trigger for it or a small cache-warming job.
- **Split restore and save** when pull requests should not write: `actions/cache/restore` everywhere, `actions/cache/save` only on the default branch. This keeps pull requests from filling the quota with near-duplicates.
- **Quota and eviction.** A repository has a total cache size limit, and entries unused for about a week are evicted. A cache keyed too finely churns the quota and evicts the useful entries. Check current usage with `gh cache list`.
- **Measure the cache step itself.** The step time for restore and for the post-job save are in the `measure` output. A restore that takes as long as the install it replaced is a loss: remove it. Windows runners extract archives slowly, so this happens there most.
- Caches are immutable per key. To record something new on every run (test timings), save under a key that includes `github.run_id` and restore by prefix.

## Checkout

`actions/checkout` fetches one commit by default. `fetch-depth: 0` (full history) is needed only for versioning from tags, changelogs, and some affected-detection tools. For affected-detection, `fetch-depth: 0` with `filter: blob:none` fetches the commit graph without file contents, which is much faster on a large repository. Turn off `lfs` and `submodules` where the job doesn't read them. `sparse-checkout` helps jobs that need one folder of a large monorepo.

## Skipping by path, with every required check still reporting

```yaml
jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      app: ${{ steps.filter.outputs.app }}
    steps:
      - uses: actions/checkout@<version>
      - uses: dorny/paths-filter@<version>     # or a few lines of `git diff --name-only`
        id: filter
        with:
          filters: |
            app:
              - 'apps/web/**'
              - 'pnpm-lock.yaml'
              - '.github/workflows/**'
  test:
    needs: changes
    if: needs.changes.outputs.app == 'true'
    ...
```

Put the lockfile, root config, and the CI files themselves in every filter. On `push` and `workflow_call` events there is no pull request to diff against: make those run everything.

## Artifacts between jobs

`actions/upload-artifact` then `actions/download-artifact` in a job that `needs:` the first. Upload only what the next job reads. Set `compression-level: 0` for content that is already compressed (archives, images, binaries), and a short `retention-days` for hand-off artifacts. For a build under about 30s, rebuilding in each job beats the round trip.

## Runners

- Jobs that don't depend on the OS belong on `ubuntu-latest`: fastest startup, cheapest minute.
- ARM Linux runners are available on GitHub-hosted plans and are often cheaper per minute; check that every tool in the job ships an ARM build.
- Larger runners are paid and need setup in the organization: **Ask**.
- On a self-hosted runner the trade-offs flip. Disks persist, so remote caches and artifact round trips may be slower than local reuse, while the number of runners caps parallelism: sharding into eight jobs on two runners queues instead of speeding up. Read queue times in the `measure` output before adding jobs.

## Docker builds

`docker/build-push-action` with BuildKit caching: `cache-from: type=gha` and `cache-to: type=gha,mode=max`, or `type=registry` for images too large for the Actions cache. Order the Dockerfile so dependency installation comes before copying source, or the cache never hits. Build each architecture on a native runner in place of emulation where possible. Service containers should declare a health check so the job starts when the service is ready, with no `sleep`.

## Measuring a branch

- A pull request is usually needed for `pull_request` workflows to run at all.
- Re-run for more samples: `gh run rerun <run-id>`, or an empty commit (`git commit --allow-empty`) which also exercises the cancel-in-progress path.
- `gh run watch <run-id> --exit-status` waits for a run. `gh run view <run-id> --log-failed` shows why one failed.
- `ci_timing.py measure --branch <branch>` reads the pull request runs of that branch.

## Starting skeleton

Adapt names and commands to the project. Fill versions from the actions' current releases.

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
concurrency:
  group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}
  cancel-in-progress: true
jobs:
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@<version>
      - <setup action with its dependency cache on>
      - run: <frozen install>
      - run: <lint>
  test:
    # same setup, then the test command; add shards when it passes 3 minutes
  build:
    # same setup, then the build command
  ci:
    name: CI passed          # require only this check in the ruleset
    if: always()
    needs: [lint, test, build]
    runs-on: ubuntu-latest
    timeout-minutes: 2
    steps:
      - run: |
          results='${{ join(needs.*.result, ' ') }}'
          for r in $results; do
            [ "$r" = success ] || [ "$r" = skipped ] || { echo "a job ended as $r"; exit 1; }
          done
```
