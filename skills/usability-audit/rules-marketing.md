# Rules for landing and pricing pages

Check each rule against the screenshots, and against the fresh reviewer's answers where the rule says so. The rules for app screens in [rules-app.md](rules-app.md) apply to these pages too. A rule is broken only when the user described in SKILL.md would be slowed, confused, or stopped. Skip a rule that is broken on paper and harmless on the screen. Cite the id in each finding.

Recommendations from these rules are hypotheses. The audit can't measure conversion, so the report says what to A/B test.

## Landing pages

The page has one job: a stranger understands what the product is and takes the next step.

| Id | Rule | How to check |
| --- | --- | --- |
| ux-60 | The headline says what the product is and who it's for, in plain words. | The five-second test from the first-look pass. "Reimagine your workflow" fails. "Invoices for freelancers, sent in a minute" passes. A stranger should be able to repeat it. |
| ux-61 | The line under the headline says what you get or how it works. | It adds something, and doesn't restate the headline in other words. |
| ux-62 | The product is shown above the fold. | A real screenshot, demo, or short video. An abstract illustration tells the visitor nothing. |
| ux-63 | There is one call to action, repeated down the page. | Its label says what happens and what it costs: "Start free, no card needed". A second action ("See how it works") is visibly quieter. |
| ux-64 | The call to action is visible without scrolling on every device. | Check the 360 px phone shot and the 1366x768 shot. |
| ux-65 | The page reads from headings alone. | Read only the headings, top to bottom. They should tell the story. Each section makes one point and names a result for the user before a feature. |
| ux-66 | Claims come with proof, near the claim. | Real customer names, logos, numbers, and reviews. Vague or invented proof is worse than none. |
| ux-67 | The usual objections are answered. | What does it cost? Is it for someone like me? How hard is it to start? What if I don't like it? |
| ux-68 | The price is one click away at most. | Hiding the price makes people assume it's high and leave. |
| ux-69 | Navigation is small. | A few links. Nothing that pulls the visitor off the page before the call to action. |
| ux-70 | No tricks. Report these and never recommend them. | Fake countdowns or stock limits, invented reviews, pre-ticked extras, a price that grows at checkout, guilt-worded decline links ("No, I don't want to save money"), ads dressed as content, a cancel flow harder than the signup flow. They also expose the owner to consumer-protection law. |
| ux-71 | The sections come in the order a stranger asks questions. | What is it, show me, why is it better, who else uses it, what does it cost, common questions, then the call to action again. |
| ux-72 | Nothing covers the page in the first seconds. | A popup or full-screen cookie wall before the headline has been read costs visitors. |

## Pricing pages

The page has one job: the visitor picks the target plan, knows what they'll pay, and doesn't feel fooled later.

| Id | Rule | How to check |
| --- | --- | --- |
| ux-80 | There are three plans, four at most, and each name says who it's for. | "Solo", "Team", "Business" with one line each on who should pick it. "Basic", "Plus", "Pro", "Max" make the visitor work it out. |
| ux-81 | The target plan is the obvious pick. | It looks different from the others (size, border, fill), carries a true "Most popular" or "Recommended" tag, and has the only primary-styled button. In the first-look pass the reviewer should name this plan. |
| ux-82 | The reason to pay more takes five seconds to find. | Each plan lists what it adds to the one below ("Everything in Team, plus:"), with the three to five differences that matter on top. Forty identical checkmark rows hide the reason. |
| ux-83 | A higher price sits beside the target plan. | A more expensive plan, or a "Contact us" tier, makes the target look reasonable. A target plan that is the most expensive thing on the page looks expensive. |
| ux-84 | The price is complete. | Per what (user, month), billed how, in which currency, with or without tax, and what is charged today. Nothing new appears at checkout. |
| ux-85 | The yearly option shows a real saving. | The saving is a number ("Save $48", "2 months free"). The monthly equivalent and the yearly total are both shown. If the toggle defaults to yearly, the yearly total is impossible to miss. |
| ux-86 | Limits are written in the user's terms. | "Up to 3 projects" passes. "10k API units" needs explaining. Limits on the lower plans should be ones a growing customer naturally reaches. |
| ux-87 | The risk is removed at the button. | "14-day free trial", "Cancel anytime", "Money back within 30 days", or "No card needed", stated next to the call to action. |
| ux-88 | Each plan's button says what happens. | "Start 14-day trial" or "Buy Team". "Get started" on every plan fails. |
| ux-89 | Cheaper plans stay visible and are quieter. | Hiding the free or cheapest plan to force an upgrade is `ux-70`. Giving it a plain outline button is fair. |
| ux-90 | Proof sits next to the price. | A quote or logo from a customer on the target plan, near that plan. |
| ux-91 | Common questions sit under the plans. | Can I switch or cancel? What happens at the limit? Is there a refund? Which payment methods? |
| ux-92 | On a phone, the target plan comes first. | Stacked plans usually put the target third, below the fold. The comparison table works without sideways scrolling or collapses into per-plan lists. |
| ux-93 | The value is framed against something the visitor already pays for. | The cost of the problem, the hours saved, or the price per use. Check that the math is true. |
