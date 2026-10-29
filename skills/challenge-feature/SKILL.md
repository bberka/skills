---
name: challenge-feature
description: "Argues against a proposed feature before any code is written. Checks whether existing features already cover the need, what the change would really cost, and how much harder the app would become to learn, then gives a build / build smaller / don't build verdict. Use when the user asks to challenge, question, push back on, or sanity-check a feature idea, or asks whether a feature is worth adding or needed at all. Don't use when the user simply asks to add or fix something."
argument-hint: "<feature idea, e.g. add snooze to bookmarks>"
---

# Challenge a feature idea

The user is unsure whether this feature belongs in the app: $ARGUMENTS

(If nothing follows the colon, the feature idea is in the user's message.)

Your job is to be the skeptic. Every feature you add makes the app a little harder to learn and to maintain, so the feature has to earn its place. Start from "don't build it" and only move off that position when the evidence says so. Write no code and edit no files during this skill.

## Panel mode

Run this skill yourself in one context by default, and spawn no subagents. Switch to the panel only when the user explicitly asks for subagents, a panel, several roles, or several perspectives ("challenge this with subagents", "get the engineer and UX view"). In that case, read [../challenge-feature-panel/SKILL.md](../challenge-feature-panel/SKILL.md) and follow it in place of the steps below. If that file isn't installed, say so and run this skill instead.

## Rules

- Don't open with praise ("great idea", "this would be useful"). Users asking for this skill already know the idea sounds good.
- Base every claim on the codebase. Read the code before judging overlap or cost, and cite `file:line`. If you can't find something, say so instead of guessing.
- When the user pushes back, hold your position unless they give you new information (a real user complaint, a use case you missed, a constraint). Enthusiasm alone isn't new information.
- If the idea holds up, say so plainly. The goal is an honest verdict, not a no every time.

## Steps

### 1. Find the real problem

Restate the feature in one sentence, then name the problem behind it: what is the user trying to get done, and what goes wrong today? If the problem isn't clear from the request or the code, ask one question and wait. Don't keep going on a guess.

### 2. Look for overlap

Search the codebase for features that already solve the same problem, fully or partly. For each one, say how much of the need it covers and what gap remains. Example: "snooze" is a timer that reopens a tab. If the app already has reminders and a read-later list, the remaining gap may be only "reopen automatically", which is a much smaller ask.

### 3. Count the cost

List what the change would really touch:

- Files, modules, and layers (UI, state, storage, background, sync)
- New data, schema changes, or migrations
- New permissions, APIs, or dependencies (for browser extensions, new manifest permissions also show users a warning)
- New settings, edge cases, and states (what happens when the device is offline, the browser closed, or the item was deleted?)
- Tests to write and code to maintain afterwards

Give a rough size: small (a few hours, one area), medium (several areas), or large (new subsystem). Be concrete. "Touches 9 files across 4 modules" is more useful than "moderate complexity".

### 4. Count the cost to users

- What new UI does it add: buttons, menus, settings, onboarding?
- What new concept does a user have to learn, and does it blur the line between existing features ("should I snooze this or add it to read later?")?
- Who actually needs this, how often, and what do they do today instead?

### 5. Cheaper alternatives

Always consider these:

- **Do nothing.** What happens if the feature is never built?
- **Extend an existing feature** to cover the gap from step 2.
- **Build a smaller version** that solves most of the problem for much less cost.
- **Change the workflow, docs, or defaults** without writing new code.

### 6. Verdict

Answer in this shape and keep it short:

```
Verdict: BUILD | BUILD SMALLER | DON'T BUILD

Problem: <one sentence>
Already covered by: <existing features and how much they cover, or "nothing">
Cost: <size> — <the 2-3 biggest cost items>
User cost: <new concepts/UI it adds>
Strongest argument against: <one sentence>
Strongest argument for: <one sentence>
Recommendation: <what to do instead, or the smallest version worth building>
```

Then stop and let the user decide. Don't start implementing, even if the verdict is BUILD, until they explicitly ask.
