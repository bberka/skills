---
name: usability-audit
description: "Audits how usable a running app, landing page, or pricing page is for a first-time, non-technical user on every device it supports. Launches the app, screenshots it on phone, tablet, and desktop, checks screen reader and keyboard access, and reports each problem with a fix. Covers the whole product, named pages or flows, or only the screens a diff, branch, or PR changed. Changes no code. Use whenever the user asks for a usability, UX, or accessibility audit or review; asks whether the app, a screen, or a flow is confusing, too complicated, or simple enough for an ordinary person; wants the UI checked on mobile or across devices; or wants a landing or pricing page to be clearer, convert better, or sell a higher plan. Use it even when they never say audit, for example: would my mom understand this signup? Don't use to restyle how a UI looks, to review code, or to build new UI."
argument-hint: "[scope, e.g. account panel, pricing page, changed files, PR 42, android only]"
---

# Usability audit

Scope: $ARGUMENTS

(If that line is empty or still shows a placeholder, take the scope from the user's message. With no scope given, audit the whole product.)

Find out whether a real person can use this product, and report what stops them. The evidence is the running app: screenshots, measurements, the accessibility tree, a keyboard walk. Agents write working UI code easily and judge poorly from code whether a person can use the result, which is why this skill looks at the app and not the source. The output is a report. No code changes.

## Files in this skill

Paths are relative to the folder that holds this file. Read each file when its step says to, not before.

| File | Read or run it when |
| --- | --- |
| [capture.md](capture.md) | Step 2, to launch the app and capture it. Read only the sections for the platforms in scope. |
| [rules-app.md](rules-app.md) | Step 5, always. |
| [rules-marketing.md](rules-marketing.md) | Step 5, only when a landing or pricing page is in scope. |
| [rules-accessibility.md](rules-accessibility.md) | Step 6. |
| `scripts/shots.mjs` | Run it to capture a web page on each device. Usage is in capture.md. |
| `scripts/tabwalk.mjs` | Run it for the keyboard walk in step 6. |
| `scripts/measure.js` | Evaluate it in a page when your own browser tool does the capturing. `shots.mjs` already runs it. |

## Who you judge for

Judge every screen as this person:

- First visit. Nobody has explained the product.
- Skims. Reads headings, button labels, and the first few words of anything longer.
- Doesn't know the product's terms or the industry's.
- On a small phone with one thumb, or a laptop with twelve other tabs open.
- After a few seconds of doubt, guesses or leaves. Doesn't read help text and doesn't report the problem.

A screen passes when this person can tell what it's for, what to do next, and what will happen when they do it.

Some of these people don't get the screen you see. One hears it through a screen reader, one item at a time. One moves with the Tab key. One has doubled the text size. They have the same tasks, and step 6 checks that they can finish too.

## Ground rules

- **Evidence comes from the running app.** Each finding points to a screenshot and a place on it, a measurement, a line of the accessibility tree, or a step of the keyboard walk. Read code only to find the platforms and screens, to launch the app, to map a diff to screens, and, once findings are written, to locate where a fix goes. If the code handles a case that the running app doesn't show, the user doesn't get it and the finding stands.
- **Be specific.** A finding says what the user sees, what they wrongly conclude or fail to do, and the change that fixes it. "Improve the visual hierarchy" is not a finding. A copy fix includes the new text.
- **Don't pad.** A screen with no problems gets one line. Twenty findings that matter are worth more than sixty that don't, because the reader acts on the first few.
- **Don't judge what you couldn't see.** A platform or screen you couldn't open goes under "Not audited" with the reason. Reading its code is not a substitute.
- **Persuade honestly.** On landing and pricing pages, aim for more signups and more people on the target plan by making the offer clear. Tricks (`ux-70`) are findings to remove. Never recommend one.
- **Change nothing.** No code edits and no commits. Stop the servers and emulators you started, and reset device settings you changed.
- **Keep your state on disk.** An audit is long enough to outlast your context. Keep `plan.md` (tasks, devices, and screens, each with a status) and `findings.md` (one entry per finding, appended as you find it) in the report folder, and build the report from them.
- **Spend image reads carefully.** Each capture is cut into screen-sized tiles (`-01.png`, `-02.png`). Read tiles, and never the `-full.png`, which is shrunk until its text is unreadable. On devices other than the main one, read tile 01 and whatever the measurements flag.

## Scope

Audit what the user asked for and nothing more. A report padded with screens they didn't ask about buries the answer they wanted. Before step 1, settle which screens are in scope and which checks to run, and write both at the top of `plan.md`.

### Which screens

| The user asked for | Screens in scope |
| --- | --- |
| The whole product, or nothing specific | The screens of the three to five main tasks. |
| Named pages or areas ("the account panel", "the landing page") | Those screens, with their states and the dialogs and menus they open. Find them by route, navigation label, or component name. If a name matches several places or none, ask. |
| A flow ("signup", "checkout") | Every screen from the flow's entry point to its end. |
| A diff ("the changed UI files", "my changes", a branch, a PR, "since <commit>") | Only the screens the diff changes. Follow "Diff scope" below. |
| Screenshots or mockups, with no app to run | The images given. |

Screens outside the scope are only a way to reach the ones inside it. Don't capture, judge, or report them. If you pass a blocker on the way, give it one line under "Outside scope" in the report and move on.

### Diff scope

1. **List the changed files.** Use the base the user named. Otherwise, for "my changes" or "the changed files" with a dirty working tree, use the uncommitted changes (`git status --porcelain`). Otherwise compare the branch with the default branch (`git diff --name-only <default>...HEAD`). For a PR, `gh pr diff <number> --name-only`.
2. **Keep the files that change what users see:** pages, routes, components, layouts, styles, themes, copy and translation files, images, icons. Drop tests, tooling, and backend-only code. If nothing is left, say the diff has no UI changes and stop.
3. **Map each file to screens.** A page or route file is its own screen. For a shared component, style, or string, search for its uses and follow the importers up to the routes that render it. A change to a global layout, theme, or design token touches every screen, so take the main tasks' screens plus one screen of each kind, and say in the report that the rest was sampled.
4. **Read the diff** to learn which elements, texts, and states changed on each screen. This tells you where to look. The judgment still comes from the running app.
5. **Audit only those screens**, on every supported device. Report a finding when it is on something the diff added or changed, or when the change made something next to it worse: a new banner pushed the main button below the fold, a new label contradicts an old one. The reader wants to know whether this change is safe to ship, so problems that were there before go under "Already there" at the end, one line each, five at most.
6. **When you can't tell whether the change caused a problem,** capture the same screen from the base version: `git worktree add <temp folder> <base>`, run it on another port, capture, then remove the worktree. Skip this when the base is slow to build.

A removed screen has nothing to capture. Check instead that nothing still links to it.

### Which checks

| The request | Run |
| --- | --- |
| Up to three screens in scope ("is the pricing page clear?", a small diff) | Steps 2 to 7 on those screens. Answer in the chat in the step 8 finding format. Keep the captures and notes in a temp folder outside the project, and write the report file only if asked. |
| More than three screens | Steps 1 to 8. |
| One aspect ("accessibility only", "just the wording", "mobile only", "android only") | Only the steps, rule files, and devices for that aspect. |
| Screenshots or mockups, with no app to run | Steps 4, 5, and 8 on the images. Mark every size and contrast finding "estimated from screenshot". Skip step 6. |

## Steps

### 1. Product, tasks, and platforms

From the README, store listing, routes, and navigation, write into `plan.md`:

- What the product is and who uses it, one sentence each.
- The things people come to do on the screens in scope (three to five for a whole product), as goals in their words ("pay an invoice", "find out what this costs"), not feature names.
- Each in-scope screen's kind: app, form, landing, or pricing.
- The supported platforms. Signs: `package.json` scripts and framework, CSS breakpoints, a PWA manifest (web); `android/`, `ios/`, `pubspec.yaml`, Expo `app.json`, `capacitor.config.*` (mobile); an `electron` dependency, `tauri.conf.json` (desktop); a `manifest.json` with `manifest_version` (browser extension). Also note a dark theme, shipped locales, right-to-left support, and tablet layouts.

Ask the user in one message, and wait, when any of these is unclear. A wrong guess here wastes the whole audit:

- Which platforms and screen sizes are supported. A web app with no mobile styles may be desktop-only on purpose, or unfinished.
- Which app to audit, when the repo holds several.
- A test account or seed data, when screens sit behind a login.
- On a pricing page, which plan most people should pick. With no answer, assume the highest plan a visitor can buy without talking to sales.

Devices:

| Platform | Capture at |
| --- | --- |
| Web, phone | 360x800 with touch (`phone`) |
| Web, tablet | 820x1180, only when a tablet layout exists (`tablet`) |
| Web, desktop | 1366x768 (`desktop`), plus 1920x1080 for landing and pricing pages (`wide`) |
| Android, iOS | the smallest phone the app supports, plus a tablet if supported |
| Desktop app | the default window size and the smallest allowed |

Add dark mode only when the app ships one. Add the longest shipped locale and one right-to-left locale for the main screens only.

Walk every task in full on the smallest device of the main platform. On other devices capture the same screens and look only for what differs. If the plan passes about 60 captures, show the user the list and let them trim it.

Done when `plan.md` lists the scope, the tasks, the devices, and every screen to capture.

### 2. Launch

Read the sections of [capture.md](capture.md) for the platforms in scope, and start the app. Use data a real account would have. A new account shows only empty states and a seeded one hides them, so capture both: first run, and an account with realistic content, including long names and long lists.

Done when each platform in scope is open, or listed under "Not audited" with the reason.

### 3. Walk the tasks

For each task, start where a new user starts: logged out, on the first screen they would land on. With a narrowed scope, go straight to the first in-scope screen and capture from there. Capture every step, including the result of each action. Also capture the states people hit:

- Empty, loading (when it lasts), success, and error. Submit a form empty and with wrong input.
- The on-screen keyboard open over a form, on phones.
- Permission prompts, cookie banners, and popups that appear before the user asked for anything.
- Offline, when the app claims to work offline.

Name captures `<platform>-<device>/<task>-<nn>-<screen>`. In `plan.md`, record for each task and device the number of steps, taps, and fields, and each point where you needed knowledge a new user wouldn't have.

Done when every screen in `plan.md` is captured or marked not reachable.

### 4. First look

You know what the app does, so you can't see what a newcomer misses. Get fresh eyes before checking any rule.

Copy tile 01 of each main screen to a new folder under neutral names (`a.png`, `b.png`), so the names reveal nothing. Spawn one subagent with a fresh context. Give it only those image paths and this brief, with the bracketed parts filled in:

```
You are looking at screenshots of a product you have never seen. You have no other
information. Open only the image files listed below, and no other file. Answer from
each image alone. Say "can't tell" when you can't.

For each screenshot:
1. After a five-second look: what is this product or screen for?
2. What can you do here? What would you tap or click first, and why?
3. What do you expect to happen when you tap that?
4. Which words, icons, or controls do you not understand?
5. [task screens] You want to [the task in the user's own words, avoiding the words
   printed on the screen]. Where exactly do you tap?
6. [pricing screens] Which plan does the page want you to pick? What do you get for
   paying more than the cheapest plan? What will you be charged today?

Images: [paths]
```

Compare its answers with the truth. Each mismatch is a finding: a wrong idea of what the product is, a first tap in the wrong place, a word not understood, a surprise about what a button does. Rank these above rule findings, because they are the nearest thing here to a test with a real person.

Without a subagent tool, answer the questions yourself before reading any UI code, writing each answer down before you check it. Mark the report "First look: not independent".

Done when each mismatch is in `findings.md`.

### 5. Rules and measurements

Read [rules-app.md](rules-app.md), and [rules-marketing.md](rules-marketing.md) when a landing or pricing page is in scope. Check each screen against the rules for its kind.

Sizes and contrast can't be judged reliably from an image, so use numbers:

- Web, Electron, extensions: read the `-measure.json` that `scripts/shots.mjs` wrote beside each capture, or evaluate `scripts/measure.js` in the page with your browser tool. Each item has a selector and a position. Look at that spot in the tile before reporting it, since an item inside a closed menu is not a finding.
- Android: element bounds come from `uiautomator dump` (capture.md).
- Where nothing can be measured, mark the finding "estimated from screenshot".

Done when every captured screen has been checked and its findings are in `findings.md`.

### 6. Screen readers and keyboards

Screenshots say nothing about these users. Run this on the main platform, for the screens of the main tasks, with [rules-accessibility.md](rules-accessibility.md).

1. **Get the tree.** The accessibility tree is what a screen reader announces: each item's role, name, and state, in reading order. `scripts/shots.mjs` writes it as `-tree.yml`. Most browser tools return it as a page snapshot, and capture.md has the Android and iOS ways.
2. **Listen to it.** Spawn a second fresh subagent. Give it only the tree files and this brief:

   ```
   Below are pages as a screen reader announces them: each item's role and name, in
   reading order. You can't see the pages and have no other information. Open only
   the files listed, and no other file. Say "can't tell" when you can't.

   For each page:
   1. What is this page for?
   2. What can you do here?
   3. You want to [task, in the user's own words]. Which item do you activate? Quote
      its line.
   4. Which items have no name, or a name that doesn't tell you what they do?
   5. Does anything come in an order that makes no sense?

   Files: [paths]
   ```

   Where it can't tell or picks the wrong item, a screen reader user is lost in the same place. Without a subagent tool, read the trees yourself before opening the matching screenshots.
3. **Compare tree and screenshot.** Anything visible that is missing from the tree, unnamed, or in a different order is a finding. So is anything in the tree that isn't on screen. Capture the tree again after an action (a failed submit, an opened dialog, a toast) to see whether the change reached it.
4. **Walk it with the keyboard.** Run `scripts/tabwalk.mjs` on each screen and read its summary: controls never reached, stops with no visible focus, focus off screen, order jumps, traps. Then finish each main task with the keyboard alone (Tab, Enter, Space, Escape, arrows), opening each dialog and menu on the way.
5. **Check the rest.** Read the `accessibility` block of the measurements, and check zoom (capture again at a 320 px wide viewport), motion, and captions.

This checks usability, not conformance. No real screen reader was used, and automated checks find well under half of real accessibility problems. Say so in the report. Never state that the product meets WCAG or any legal standard.

Done when each main task has a keyboard result and its findings are in `findings.md`.

### 7. Across devices

Compare the same screen on each device. Look for content or actions that are on one and missing on another, cut-off text, a main button below the fold or behind the keyboard, anything that needs hover, sideways scrolling, and controls out of thumb reach.

Done when every screen captured on more than one device has been compared.

### 8. Report

Give each finding a severity:

| Severity | Meaning |
| --- | --- |
| Blocker | The user can't finish the task, or does the wrong thing without knowing: buys the wrong plan, deletes data, sends something unintended. A task that can't be finished by keyboard or screen reader is a blocker for those users. |
| Major | Most users hesitate, backtrack, or misunderstand. On landing and pricing pages: likely to leave, or to pick a plan they didn't mean to. |
| Minor | Slows or annoys people, and they still get through. |

Tag the evidence: **first look**, **measured**, **keyboard**, or **rule ux-N**. Merge repeats into one finding that lists every screen. Leave out matters of taste unless they hurt understanding.

Landing and pricing recommendations are hypotheses, because this audit can't measure conversion. For the larger ones, name the A/B test and the number that should move.

Once the findings are final, you may search the code for where each fix goes and add `file:line`.

Write `usability-audit/<YYYY-MM-DD>/report.md` at the project root, beside the captures, unless the user names another place. Don't commit it. Use this template:

```
# Usability audit: <product>, <date>

Scope: <whole product | the pages or flow named | the diff, with its base and the screens it maps to>
Audited: <platforms, devices, themes>, <n> captures
Not audited: <platform or screen, and why>
First look: independent | not independent
Accessibility: checked from the accessibility tree and a keyboard walk on <platform>.
Not a WCAG conformance audit. No real screen reader was used.

## Verdict
<Three to five sentences. Can a first-time user do the main tasks? What are the two
or three biggest things in the way?>

## Tasks
| Task | Device | Steps | Result | Where it breaks |
| --- | --- | --- | --- | --- |
| Pay an invoice | phone 360 | 7 | done, after a wrong first tap | step 3 |
| Pay an invoice | keyboard only | 19 key presses | stuck | step 4: the date picker can't be opened |

## Findings

### 1. <What the user gets wrong, in one line>
Severity: Blocker | Major | Minor
Evidence: first look | measured | keyboard | rule ux-N
Affects: everyone | screen reader users | keyboard users | <device>
Screen: ![](<capture path>) <plus the other devices affected>
Where: <the element and its position on the screen, or its line in the tree>
What happens: <what the user sees, what they conclude, what they do>
Fix: <the concrete change, with new copy in quotes>
Effort: copy | layout | flow
Code: <file:line, if found>

## Quick wins
<Copy changes and one-line fixes, as a checklist>

## Landing page / Pricing page
<Only when in scope: the result of the five-second test, the plan the page steers to
against the target plan, and the hypotheses to test>

## Working well
<A few things that work and that the fixes shouldn't break>

## Already there
<Diff scope only: problems on these screens that the change didn't cause, one line
each, five at most>

## Outside scope
<Only if you passed a blocker on a screen that wasn't in scope: one line each>
```

Tell the user the report path and the verdict, then stop. Fix nothing until they ask.
