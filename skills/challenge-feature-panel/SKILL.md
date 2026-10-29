---
name: challenge-feature-panel
description: "Puts a feature idea in front of a panel of subagents (engineer, UX designer, everyday user, product owner, advocate) that each review it independently, then weighs their reports into one build / build smaller / don't build verdict. Spawns five subagents, so it costs more than challenge-feature. Manual only."
argument-hint: "<feature idea> [roles: engineer,ux,user,product,advocate,...]"
disable-model-invocation: true
---

# Challenge a feature idea with a panel

The user is unsure whether this feature belongs in the app: $ARGUMENTS

(If nothing follows the colon, the feature idea is in the user's message.)

You chair a panel. Each panelist is a subagent with one role. They review the idea separately, and you weigh their reports. Start from "don't build it": every feature makes the app harder to learn and maintain, so it has to earn its place. Neither you nor the panel writes code or edits files during this skill.

## 1. Frame the idea

Restate the feature in one sentence and name the problem behind it: what is the user trying to get done, and what goes wrong today? If the problem isn't clear from the request or the code, ask one question and wait.

Then scan the project just enough to brief the panel:

- What the app is for (README, manifest, package description)
- Where the relevant code lives: entry points, UI, storage, background code
- Existing features that touch the same problem

Don't form or share an opinion yet. The brief gives the panel facts and pointers. If it includes your view, every panelist will start from it.

## 2. Pick the panel

Use the five default roles in [roles.md](roles.md): engineer, ux, user, product, advocate. If the user names roles, use those instead. A role not in the file, such as `security`, `accessibility`, `power-user`, or `mobile`, gets a brief you write in the same shape as the ones in roles.md.

## 3. Run the panel

Spawn one subagent per role, all at once so they run in parallel, and wait for every report. In Claude Code, use the Agent tool with `run_in_background: false`. In Codex, use `spawn_agent`, then wait. If your agent has no subagent tool, play each role yourself one at a time and write out each report in full before starting the next. Tell the user the panel ran in one context, so the reports are less independent than they would be from separate agents.

Give every panelist the same brief, its own role from roles.md, and the report format below. Panelists don't see each other's reports.

```
You are the <ROLE> on a panel reviewing whether a feature should be added to this app.
Work read-only: read and search the code, but don't edit files or write code.

Feature: <one sentence>
Problem it is meant to solve: <one sentence>
App: <what the app is for>
Places to start reading: <paths>
Existing features that may overlap: <names and paths>

Your role:
<role brief from roles.md>

Rules:
- Base claims on the code and cite file:line. If you couldn't check something, say so.
- Don't praise the idea. Report what you found.
- Stay in your role. Leave other angles to the other panelists.
- Keep the report under 400 words.

Report in exactly this format:
Role: <role>
Vote: BUILD | BUILD SMALLER | DON'T BUILD
Confidence: high | medium | low
Findings:
- <finding, with evidence>
Biggest concern: <one sentence>
Biggest benefit: <one sentence>
Smallest version I'd accept: <one sentence, or "none">
I'd change my vote if: <what new information would do it>
```

## 4. Weigh the reports

Weigh the evidence instead of counting votes. One well-supported finding beats three hunches. The advocate makes the case for building on purpose, so treat its report as the best case and don't count its vote.

When panelists disagree on a fact ("this reuses the existing alarm code" against "there is no alarm code"), read the code yourself and settle it. Name the panelist who was wrong.

## 5. Verdict

Answer in this shape:

```
Verdict: BUILD | BUILD SMALLER | DON'T BUILD

Problem: <one sentence>

| Role | Vote | Main reason |
| --- | --- | --- |
| engineer | ... | ... |
| ux | ... | ... |
| user | ... | ... |
| product | ... | ... |
| advocate (not counted) | ... | ... |

Agreed on: <points most panelists raised>
Settled disputes: <claim — what you checked — who was right>
Cost to build: <size, and the 2-3 biggest items>
Cost to users: <new UI and concepts>
Strongest argument against: <one sentence>
Strongest argument for: <one sentence>
Recommendation: <what to do instead, or the smallest version worth building>
```

Then stop and let the user decide. If they push back, hold the verdict unless they bring new information. Enthusiasm alone isn't new information. Don't start implementing, even on a BUILD verdict, until they explicitly ask.
