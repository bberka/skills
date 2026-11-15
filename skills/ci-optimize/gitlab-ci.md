# GitLab CI

How the levers in [levers.md](levers.md) are written for GitLab CI, and the traps specific to it. Keyword behaviour differs between GitLab versions and tiers: check the CI/CD YAML reference for the instance's version before relying on one.

## Merge rules

`scripts/ci_timing.py rules --provider gitlab` reads the project's merge settings. It needs a token with `read_api` (`GITLAB_TOKEN`, or a signed-in `glab`) for anything but public pipeline data.

- **GitLab gates on the whole pipeline**, not on named checks. With "Pipelines must succeed" on, every job without `allow_failure: true` blocks the merge. So the gate is: all jobs in the merge request pipeline that are not allowed to fail.
- **"Skipped pipelines are considered successful"** decides what happens when your `rules:` produce no pipeline for a merge request. Off (the default), a merge request with no pipeline cannot merge. Check it before adding `workflow:rules` or `rules:changes` that can leave a merge request with nothing to run, and keep at least one cheap job that always runs if it is off.
- **`allow_failure: true` takes a job out of the gate.** Adding it is making a check optional: **Ask**.
- **Fast-forward and semi-linear merge methods** require a rebase when the target moves, and each rebase re-runs the pipeline. Merge trains and merged-results pipelines change this. All are project settings: **Ask**.
- **External status checks and approval rules** (paid tiers) can also block merges. They don't change pipeline time.

## One pipeline per push

A push to a branch with an open merge request can start two pipelines, a branch pipeline and a merge request pipeline. The standard fix:

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH
```

`rules:changes` compares correctly only in merge request pipelines. In branch pipelines it compares against the previous push, which skips work it should not.

## Cancel superseded pipelines

```yaml
default:
  interruptible: true
```

together with the project setting "Auto-cancel redundant pipelines" (and `workflow:auto_cancel:on_new_commit` on versions that have it). Mark deploy and release jobs `interruptible: false`: a pipeline stops being cancellable once such a job has started.

## Shape

- Stages run in order; jobs in a stage run in parallel. `needs:` lets a job start as soon as the jobs it names finish, ignoring stage order. Put `needs: []` on jobs that depend on nothing, so lint and tests start at once and don't wait for a build stage.
- `needs:` also limits artifact downloads to the named jobs. Without it a job downloads the artifacts of every earlier stage: set `dependencies: []` on jobs that need none.
- `parallel: N` splits a job into N copies with `CI_NODE_INDEX` and `CI_NODE_TOTAL`, for runners with a shard flag or for `scripts/split_by_time.py`. `parallel:matrix` runs variants.
- For monorepos, `rules:changes` per job, or child pipelines (`trigger:include`) per package.
- Shared setup: `extends`, `!reference`, `include`, or CI/CD components.

## Caching

```yaml
.deps:
  cache:
    key:
      files: [pnpm-lock.yaml]      # key follows the lockfile, shared across branches
    paths: [.pnpm-store]
    policy: pull                    # most jobs only read

install:
  extends: .deps
  cache:
    policy: pull-push               # one job writes
```

- Key on lockfile contents with `cache:key:files`. A key holding `$CI_COMMIT_REF_SLUG` gives every branch its own cold cache.
- `policy: pull` on consumers saves the upload at the end of each job. Uploading an unchanged cache is a common hidden cost: look at the last lines of a job log.
- Protected and unprotected branches use separate caches by default, so merge request pipelines cannot read the default branch's cache. The project setting "Use separate caches for protected branches" controls this. Turning it off lets any branch write a cache the default branch reads, which is a security trade-off: **Ask**.
- Cache paths must be inside the project directory. Point the package manager's store there (`npm ci --cache .npm`, `PIP_CACHE_DIR`, `GOMODCACHE`, `CARGO_HOME`).
- Whether the cache is fast depends on the runner: local disk on a single runner, or object storage shared by a fleet. With distributed runners and no shared cache configured, hits are luck. Ask who runs the runners when hit rates look random.
- Faster archiving: `FF_USE_FASTZIP: "true"` with `CACHE_COMPRESSION_LEVEL: fastest` and `ARTIFACT_COMPRESSION_LEVEL: fastest`. Safe; measure the difference.
- Use artifacts for what one job builds and a later job in the same pipeline must have. Use cache for what merely speeds a job up. A job must work with an empty cache.

## Fetching and images

- `GIT_DEPTH: "20"` (or lower) for a shallow fetch; jobs that read history or tags need more. `GIT_STRATEGY: none` for jobs that use only artifacts. `GIT_SUBMODULE_STRATEGY: none` unless needed.
- Small images start faster: a slim or alpine variant that already holds the toolchain, pinned by version, never `latest`. An `apt-get install` in `before_script` on every job is a sign to build a project CI image once and reuse it.
- `image:pull_policy: if-not-present` avoids a registry round trip when the runner allows it.

## Docker builds

BuildKit with a registry cache: `docker buildx build --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache,mode=max`. Kaniko and Buildah are the daemonless options. Order the Dockerfile so dependency layers come before source.

## Retries

```yaml
default:
  retry:
    max: 2
    when: [runner_system_failure, stuck_or_timeout_failure, scheduler_failure]
```

Retries only infrastructure failures. A blanket `retry: 2` hides flaky tests and doubles the time of every real failure: **Ask** before adding one.

## Timeouts and runners

`timeout:` per job, well under the project default. Runner sizing and `concurrent` are set by whoever runs the runners: when the `measure` output shows long queue times, the fix is there and not in the YAML. Report it.

## Measuring a branch

- `ci_timing.py measure --provider gitlab --branch <branch> --event ''` reads that branch's pipelines; `--event pull_request` selects merge request pipelines.
- The API gives job times and queue times but no step times. Read a job log for the split: each section is timestamped.
- Re-run with `glab ci retry`, the pipeline page, or an empty commit.

## Starting skeleton

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

default:
  image: <pinned toolchain image>
  interruptible: true
  timeout: 15m
  cache:
    key: { files: [<lockfile>] }
    paths: [<store inside the project dir>]
    policy: pull

stages: [check]

install:
  stage: .pre
  cache: { policy: pull-push }
  script: <frozen install>

lint:  { stage: check, needs: [install], script: <lint> }
test:  { stage: check, needs: [install], script: <test> }
build: { stage: check, needs: [install], script: <build> }
```

When the install is fast with a warm cache, drop the `install` job and let each job install for itself with `policy: pull`, saving a job startup on the pole. Measure both.
