# Levers

Every way to make CI faster, grouped by what it acts on. Work through the groups in order: the early ones are cheap and safe, the late ones save the most and need a yes.

Each lever has a class:

- **Safe**: the same checks run on the same code with the same pass or fail meaning. Apply it, then keep it only if the measurement shows a gain.
- **Ask**: it changes what is checked, when, how the app is built, or what CI costs. Ask first, and ship it with the guardrail named.

Provider syntax is in [github-actions.md](github-actions.md) and [gitlab-ci.md](gitlab-ci.md). Tool specifics are in [stacks.md](stacks.md).

## 1. Shape of the pipeline

| Lever | Spot it by | Class |
| --- | --- | --- |
| **Run independent checks in parallel.** Lint, typecheck, test, and build as separate jobs, so the wait is the slowest one and not the sum. | One job running them in sequence, with a step-time sum well above its longest step. | Safe. Each new job pays startup and install again (20 to 60s), so split only steps longer than that, and expect runner minutes to rise. |
| **Run steps in parallel inside one job.** When startup and install dominate, background the commands in one job and wait for all. | Several short jobs, each mostly setup. | Safe. Keep each command's output and exit code separate so a failure is still readable. |
| **Remove a dependency between jobs that the downstream job doesn't use.** | A job that waits on another and takes no artifact or output from it. | Safe when the order was accidental. **Ask** when it is a deliberate gate ("build packages only after tests pass"): removing it shortens the wait and spends minutes on runs that would have stopped early. |
| **Merge tiny jobs.** Per-job billing rounds up to a full minute, and each job pays startup. | Many jobs under 30s. | Safe. Keep the job names that the merge rules require. |
| **Build once, pass the result on.** | Several jobs running the same build. | Safe. Upload and download have a cost too: for a build under about 30s, rebuilding is often faster. Measure. |
| **Fail fast.** Put the quickest, most-often-failing check first, and stop sibling shards when one fails. | A 10-minute job that fails on a lint error in its last step. | Safe for shards of one suite. Leave fail-fast off for matrices that diagnose (OS, version), where the user wants to see every failure. |

## 2. Runs that should not happen

| Lever | Spot it by | Class |
| --- | --- | --- |
| **Cancel superseded runs.** A new push to a pull request cancels the run for the old commit. | Many overlapping runs on one branch, none cancelled. | Safe on pull requests. Never cancel default-branch, release, or deploy runs. |
| **One run per push.** | The same commit running on both the branch-push and pull-request events. | Safe: restrict the push trigger to the default branch. |
| **Skip unaffected work with path filters.** Docs-only changes skip the build; a change in one app skips the others' jobs. | Run history where a README edit ran everything. | Safe when every required check still reports on the skipped pull request (see the provider file). List shared inputs (lockfile, CI config, root config) in every filter. |
| **Skip draft pull requests** for the expensive jobs. | Long jobs on drafts. | **Ask**: authors lose early feedback. |
| **Trim trigger events.** Label, edit, and comment events rarely need a full run. | Runs with no new commit. | Safe. |
| **Slow down or drop schedules** that find nothing. | A cron running the same suite as every push. | **Ask**. |

## 3. Setup and caching

| Lever | Spot it by | Class |
| --- | --- | --- |
| **Cache dependencies, keyed on the lockfile.** | An install step of 20s or more that downloads every run. | Safe. Measure: restoring a large cache can cost more than the download it replaces, mostly on Windows runners and for package managers with fast registries. Keep it only when the job got faster. |
| **Make caches reachable.** A cache saved on a pull request branch is usually invisible to other branches. | A cache that misses on the first run of every pull request. | Safe: save on the default branch, restore everywhere. |
| **Cache what tools compute**, not only what they download: compiler and bundler caches, lint and typecheck caches, test transform caches, browser binaries. | The tool has a cache flag or directory and CI starts cold. | Safe, with a key that includes the tool version and config. A cache keyed too loosely serves stale results; when unsure, key tighter. |
| **Stable cache keys.** | Keys holding a commit SHA, run id, or date, so nothing ever hits. | Safe. |
| **Install less.** Skip browsers, SDKs, system packages, and dev tools in jobs that don't use them. Use the frozen or offline install mode. | Setup steps whose output no later step touches. | Safe. |
| **Use what the runner image already has** in place of installing a toolchain. | A setup step that downloads a version the image ships. | Safe when the version is pinned somewhere (`global.json`, `.nvmrc`, `rust-toolchain.toml`). **Ask** if it would unpin the version. |
| **Shallow, narrow checkout.** | Full history fetched in jobs that never read it; submodules or LFS pulled and unused. | Safe. Versioning, changelog, and affected-detection steps do need history: check before cutting. |
| **Share setup** through a reusable action or template, so a fix lands everywhere. | Copy-pasted setup blocks that have drifted. | Safe. Saves no time by itself; it makes the other levers stick. |
| **Replace sleeps with readiness checks.** | `sleep 30` before tests, fixed waits inside tests. | Safe in CI config. Inside test code it is a test change: **Ask**. |

## 4. The slow step itself

| Lever | Spot it by | Class |
| --- | --- | --- |
| **Use every core.** Runner CPUs often sit idle because the tool defaults to one worker or CI caps it. | Worker or job count hard-coded low, or never set. | Safe. Measure: more workers than cores makes it slower. |
| **Shard a long test job** across parallel jobs. | A test step over about 3 minutes that dominates the pole. | Safe. Runner minutes rise by one setup per shard. Stop adding shards when a shard's test time falls to about twice its setup time. |
| **Fill shards by recorded time.** Splitting by file count leaves one shard slow; splitting by last run's durations evens them. | Shards whose times differ by more than about 30%. | Safe. Needs a timings file saved from the default branch. See "Shards by recorded time" below. |
| **Turn on incremental or cached mode** in the tool. | A tool with an incremental mode running from scratch. | Safe with a correct cache key. |
| **Stop doing the work twice.** | A build that typechecks, then a typecheck job; tests run once for results and once for coverage; a compile before a publish that compiles again. | Safe when one run really covers the other. Check the flags. |
| **Collect artifacts only on failure.** Traces, videos, and coverage uploads on every green run cost time. | Upload steps of 10s or more on passing runs. | Safe when nobody reads them on green runs. Coverage that feeds a required check stays. |
| **Swap a slow tool for a faster one of the same kind**: a native type checker, a Rust-based linter or formatter, a faster test runner, bundler, or package installer. | One tool's step is most of the pole, and a faster equivalent exists. | **Ask**. Rule sets and results differ between tools. Guardrail: run both on the codebase, show the differences in what they report, and keep the old tool in a nightly or default-branch job until the user trusts the new one. A drop-in replacement the project's own toolchain ships is still a tool change: say so. |
| **Move to a faster or cheaper runner.** Linux in place of Windows or macOS for OS-independent jobs; ARM; more cores. | A job that doesn't need its OS, or a CPU-bound step. | Safe when moving an OS-independent job to a cheaper standard runner. **Ask** for paid larger runners. |

## 5. Checking less per pull request

All of these are **Ask**. They trade certainty for speed, and they are where the largest savings usually are.

| Lever | Guardrail to ship with it |
| --- | --- |
| **Run only the tests the diff can reach** (affected packages, dependency-graph test selection, changed-files modes). | The full suite still runs on the default branch after merge, or in the merge queue. Fall back to the full suite when the lockfile, CI config, shared config, or anything the tool cannot trace changes. Run both side by side for a week and compare failures before trusting it. |
| **Build only affected packages** in a monorepo. | Same as above, and a full build on the default branch. |
| **Trim the pull request matrix** to one OS or version, with the full matrix after merge or nightly. | Someone watches the post-merge run: a failure there needs a notification, or it goes unseen. |
| **Move slow suites** (end-to-end, packaging, visual, performance) off the pull request. | Same. Name who is told when the post-merge run fails. |
| **Make a slow check non-required.** | The user changes the merge rules, or approves the change. |
| **Remove or merge redundant tests.** | A test change, outside CI config. Propose it; a test-quality pass is separate work. |
| **Retry flaky jobs automatically.** | Hides real failures. Prefer fixing or quarantining the flaky test. Retry only infrastructure failures (runner lost, network), which providers can tell apart. |

## What does not count as a speedup

- Making a failing step pass by ignoring its result.
- Deleting or skipping tests without a yes.
- A change measured once, on a run that happened to get a fast runner.
- A cache that hides a missing dependency declaration, so a cold run fails.

## Shards by recorded time

Splitting by time needs last run's durations and a list of test files.

1. Make the test runner write a JUnit XML report (nearly all can), in every shard.
2. On the default branch, keep the reports where the next run can read them: a cache entry saved under a fresh key each run and restored by prefix, or an artifact from the last successful default-branch run.
3. In each shard, pick its files:

   ```bash
   <list test files> | python3 scripts/split_by_time.py --shard 2 --of 4 --timings 'reports/**/*.xml' > shard-files.txt
   <test runner> $(cat shard-files.txt)
   ```

   Files with no recorded time get the median, so new tests spread evenly. With no timings at all it falls back to an even split by count, so the first run works.
4. Check the shard times after two runs. They should sit within about 15% of each other. One file longer than a whole shard's share cannot be balanced: split that file, or accept it.

Copy `split_by_time.py` into the project (for example `scripts/ci/`), since CI cannot reach this skill's folder. Runners with timing-based splitting built in, or a plugin for it, are in [stacks.md](stacks.md): prefer those when the project already has one.
