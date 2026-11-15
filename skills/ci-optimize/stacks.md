# Stacks

What to look for per language and tool. Read only the sections the project uses. Tool names here are families to look up, since flags and versions move: confirm each against the tool's current docs and the version in the project's lockfile before writing it into CI.

Each item is **Safe** unless marked **Ask** (see [levers.md](levers.md) for what the classes mean).

## JavaScript and TypeScript

**Install**
- Frozen installs only: `npm ci`, `pnpm install --frozen-lockfile`, `yarn install --immutable`, `bun install --frozen-lockfile`.
- Cache the package manager's store (not `node_modules`), keyed on the lockfile. The setup action's built-in cache does this.
- Skip what the job doesn't use: browser downloads (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD`, `PUPPETEER_SKIP_DOWNLOAD`, `CYPRESS_INSTALL_BINARY=0`), optional dependencies, and postinstall scripts in jobs that only lint.
- In a monorepo, a job for one package can install only that package and its dependencies (`pnpm install --filter <pkg>...`).
- Switching package manager for speed changes the lockfile and resolution: **Ask**.

**Typecheck**
- `tsc --noEmit` with `incremental` and a cached `.tsbuildinfo`; project references with `tsc -b` in monorepos.
- `skipLibCheck: true` removes most declaration-file checking time. It is a tsconfig change that hides errors in dependencies' types: **Ask**.
- A build that already typechecks, plus a separate typecheck job, checks twice. Keep one.
- The native TypeScript compiler (TypeScript 7, `tsgo`) is several times faster than the JavaScript one. Moving to it is a compiler change: **Ask**, and compare the diagnostics of both on the codebase first.

**Lint and format**
- ESLint: `--cache --cache-strategy content` with the cache file cached in CI. Type-aware rules build the whole type graph and usually dominate lint time: find out with `TIMING=1`.
- Rust-based linters and formatters (oxlint, Biome, dprint) run in a fraction of the time. Their rule sets differ from ESLint and Prettier: **Ask**. Guardrail: map the project's enabled rules to the new tool, list the ones with no equivalent, and either keep ESLint for only those rules or get a yes to drop them. Turning on every rule the new tool has will add failures, which is a change in what is checked too.
- Lint only changed files on pull requests: **Ask** (cross-file rules miss things), with a full lint on the default branch.

**Tests**
- Vitest: `vitest run` in CI (never watch mode). Tune the pool and worker count to the runner's cores. `--shard=i/n` for shards; a blob reporter merges shard reports. Disabling isolation (`--no-isolate`) or changing the pool is a large speedup for suites that allow it, and changes test behaviour: **Ask**.
- Jest: `--ci`, `--maxWorkers` set to the core count, `--shard=i/n`. Cache its transform cache directory.
- Playwright: `--shard=i/n` with the blob reporter, `workers` matched to cores, `fullyParallel` where tests allow. Cache the browser directory keyed on the Playwright version, and still run the system dependency install when a job needs it. Install only the browsers the job uses. Traces and videos `on-first-retry` or `retain-on-failure`, never `on`.
- Coverage: one run that both tests and collects coverage, not two.
- Tests the diff can reach (`vitest --changed <base>`, `jest --changedSince`, `vitest related`): **Ask**, with the guardrails in levers.md.
- Time-balanced shards: Playwright and Vitest shard by file count. Use `scripts/split_by_time.py` with their JUnit reports when shards are uneven.

**Build**
- Cache the bundler's cache: `.next/cache`, Vite's cache dir, Turbo's `.turbo`, Nx's cache, webpack's filesystem cache.
- Monorepo task runners (Turborepo, Nx, and the like): every task needs correct `inputs` and `outputs` or the cache never hits, and remote caching needs to be both read and written somewhere. Environment variables in the task hash that change every run (commit SHA, run id) defeat it. Remote cache services cost money or setup: **Ask**.
- Affected-only builds and tests (`turbo run test --filter=...[origin/main]`, `nx affected`): **Ask**, guardrails in levers.md. They need enough git history to find the merge base.
- Swapping the bundler or minifier changes what ships: **Ask**.

## .NET

- Restore once with `--locked-mode` when lock files exist, then `--no-restore` on build and `--no-build` on test, so nothing compiles twice.
- NuGet cache: the setup action's cache input (it needs `packages.lock.json`) or a cache on the global packages folder keyed on the project files. Measure on Windows runners, where restoring the cache is often slower than restoring from nuget.org.
- A setup step that downloads an SDK the runner image already has costs 15 to 30s on Windows. Pin the SDK in `global.json` with a `rollForward` policy and check the image's installed versions before removing or keeping the step.
- Build only the project graph the job needs (the test project, not the whole solution).
- Tests: Microsoft.Testing.Platform and xUnit v3 run assemblies in parallel; check `maxParallelThreads` and that collections are not serialized by accident.
- Native AOT and trimmed publishes are the slow step in packaging jobs, and code generation time is fixed per target. Savings come from building fewer targets per pull request (**Ask**) or from not gating them behind slower jobs.
- Cross-compile platform checks on one Linux runner (`-r win-x64 -p:EnableWindowsTargeting=true`) instead of a Windows runner, when the job compiles but does not run.

## Rust

- `Swatinem/rust-cache` or sccache; never cache all of `target/` without a key on the toolchain and lockfile.
- `CARGO_INCREMENTAL=0` in CI: incremental artifacts bloat caches and help little on a clean runner.
- `cargo nextest` runs tests faster than `cargo test` and can partition (`--partition count:i/n`). It skips doctests, which need a separate `cargo test --doc`. A runner change: **Ask**.
- A faster linker (mold, lld) and lower debug info for CI profiles (`debug = 0` or `line-tables-only`) cut link and compile time. Profile changes in `Cargo.toml` affect local builds too: scope them to a CI profile or env vars.
- `cargo check`/`clippy` and `cargo test` build different artifacts. Run them in separate jobs with separate caches.
- Build the feature and target matrix on pull requests only as far as the user wants: **Ask** before trimming.
- `cargo build --timings` shows which crates dominate.

## Python

- `uv` installs many times faster than pip and reads the same requirements. As an installer in CI only (`uv pip install`), it is Safe when the resolved versions are identical: confirm with a lockfile or `pip freeze` diff. Moving the project to uv's own lockfile: **Ask**.
- Cache the installer's cache dir (pip, uv, poetry) keyed on the lockfile.
- `pytest -n auto` (pytest-xdist) uses every core: Safe when tests are independent, and the first run will show whether they are. `pytest-split` balances shards by recorded durations.
- Ruff replaces flake8, isort, and black at a fraction of the time: a tool change, **Ask**.
- mypy: cache `.mypy_cache`; the daemon doesn't help on a clean runner.

## Go

- The setup action caches the module and build caches. Check the build cache is included: it is what makes `go test` skip unchanged packages.
- `go test ./...` already runs packages in parallel; `-p` and `-parallel` tune it. `-race` and `-count=1` are deliberate slowdowns: leave them unless the user says otherwise.
- `golangci-lint` has its own cache dir; its action caches it.
- `go vet` runs as part of `go test`. A separate vet step repeats it.

## JVM and Android

- Gradle: the official Gradle setup action handles the dependency and build cache. Turn on the configuration cache and the build cache (`org.gradle.caching=true`), and `org.gradle.parallel=true`. Don't use the daemon's absence as a reason for `--no-build-cache`.
- Write the Gradle cache only from the default branch (the action's read-only mode on pull requests).
- Build only the variant and ABIs the check needs (`assembleDebug`, one ABI) on pull requests: **Ask** if the pull request build is something reviewers install.
- Maven: cache `~/.m2/repository`, run with `-T 1C` for parallel modules, `-o` after a warm cache where the project allows.
- Lint and unit tests don't need an emulator. Emulator tests are slow: shard them or move them off the pull request (**Ask**).

## Docker and services

- BuildKit layer cache to the provider's cache or a registry, `mode=max` so intermediate stages are cached too.
- Dockerfile order: manifests and dependency install before `COPY . .`. A `.dockerignore` that excludes `node_modules`, build output, and `.git`.
- Cache mounts (`RUN --mount=type=cache`) for package manager stores.
- Multi-architecture images: build each on a native runner and merge the manifests. Emulated builds are several times slower.
- Start only the services a test job uses, with health checks in place of sleeps.
- Don't build the image on pull requests that don't touch it. Don't push from pull requests.

## Any stack: reading a slow step

When step times don't say why a step is slow, get the tool's own breakdown before changing anything: `TIMING=1` for ESLint, `tsc --extendedDiagnostics`, `vitest --reporter=verbose`, `pytest --durations=20`, `cargo build --timings`, `dotnet build -bl` or `-clp:PerformanceSummary`, Gradle `--scan` or `--profile`, `docker build --progress=plain`. One slow test file or one slow package is a different fix from a slow suite.
