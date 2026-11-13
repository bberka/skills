# Rules for app screens

Check each rule against the screenshots. Rules marked "Measure" use numbers from `scripts/measure.js` or the device, not an estimate from the image. A rule is broken only when the user described in SKILL.md would be slowed, confused, or stopped. Skip a rule that is broken on paper and harmless on the screen. Cite the id in each finding.

## Every screen

| Id | Rule | How to check |
| --- | --- | --- |
| ux-1 | The screen has one job, and its heading says what it is. | Cover everything but the heading. Can you still say what the screen is for? |
| ux-2 | There is one main action. It is visible without scrolling, and it is what most people came to do. | Count the buttons styled as primary. Two of equal weight make the user choose blind. None means they hunt. |
| ux-3 | A button says what happens when you press it. | Labels are a verb and an object: "Save changes", "Send invoice". "OK", "Submit", "Continue", and "Yes" fail when the user can't predict the next screen. |
| ux-4 | Words are the ones users say. | No internal names, abbreviations, or technical terms (sync, token, instance, payload, null). One thing has one name everywhere: not "project" here and "workspace" there. |
| ux-5 | Text is short and front-loaded. | People read the first few words. Sentences run under about 20 words, and the key word comes first. A paragraph of help text is unread text. Aim for the reading level of a 12-year-old. |
| ux-6 | Things you can press look pressable, and nothing else does. | Buttons look like buttons and links like links. Plain text or a flat icon that turns out to be a control fails, and so does decoration that looks tappable. |
| ux-7 | Icons have labels. | Only a few icons are understood without text: search, close, back, home, menu, play. Everything else needs a visible label. |
| ux-8 | The user knows where they are and how to get back. | A screen title, the current section marked in the navigation, and a visible back or close control. No dead ends. |
| ux-9 | Every action gets a visible response. | After a tap something changes: a loading state, a confirmation, the new item appearing. A button that seems to do nothing gets pressed twice. |
| ux-10 | Errors say what went wrong and what to do, next to the problem. | Plain words, no codes, no blame, and the user's input is kept. "Invalid input" fails. "Enter a date after today" passes. |
| ux-11 | Empty states explain and offer the first step. | An empty list says what will appear here and has the button that adds the first item. |
| ux-12 | Destructive actions are hard to hit by accident and easy to reverse. | They sit apart from routine actions, name what they destroy ("Delete 3 photos"), and can be undone. Undo beats "Are you sure?". |
| ux-13 | Choices are few, and a sensible one is already picked. | More than about seven equal options at one level slows everyone down. Group them, set a default, or move rare ones behind "More". |
| ux-14 | The layout follows what people already know. | Logo at top left goes home. Search is at the top. Cart and account are at top right. Phones have tabs at the bottom. Settings sit behind a gear or the profile. Inventing a new pattern costs every user a moment. |
| ux-15 | The user never has to remember something from an earlier screen. | A confirmation step repeats what is being confirmed. Codes, totals, and choices stay visible when they're needed. |
| ux-16 | The most important thing is the most visible thing. | Blur the screenshot or squint. What stands out first should be the heading and the main action. Related items sit together and unrelated ones apart. |
| ux-17 | Nothing interrupts before the user has got something. | No signup wall, tour, popup, rating request, or permission prompt on arrival. Ask for a permission at the moment it's needed, and say why. |
| ux-18 | The screen is not crowded. | Remove an element in your head. If nobody would miss it, it's a finding. Rarely used controls go one level down. |

## Forms

| Id | Rule | How to check |
| --- | --- | --- |
| ux-20 | Ask only for what is needed now. | Every extra field loses people. Question each one. Optional fields are marked or removed. |
| ux-21 | Labels sit above fields and stay visible. | Placeholder text used as the label disappears when typing starts, and fails. |
| ux-22 | One column, one question per row. | Side-by-side fields get skipped, on phones most of all. |
| ux-23 | The right keyboard and autofill appear. | Email, number, and phone fields bring up the matching keyboard. Paste works. Formats are forgiving: spaces in a phone or card number are accepted. |
| ux-24 | Rules are shown before the user breaks them. | Password requirements appear up front. Validation runs when the user leaves a field, not on each keystroke. A password field can be shown. |
| ux-25 | Long forms show progress. | The user sees how many steps there are and which one they are on. |
| ux-26 | An account is not demanded before any value. | Guest use, a single sign-on button, or sign-up after the first result. |

## Phones and touch

| Id | Rule | How to check |
| --- | --- | --- |
| ux-30 | Tap targets are big enough. Measure. | 44x44 pt on iOS, 48x48 dp on Android, and on the web 44x44 CSS px for main controls with a hard floor of 24x24 (WCAG 2.2 AA). Leave about 8 px between neighbors. |
| ux-31 | The main action is in thumb reach and never behind the keyboard. | It sits in the lower half or in a bottom bar, and stays visible with the keyboard open. |
| ux-32 | Text is readable without zooming. Measure. | Body text is 16 px or more on the web, and nothing is under 12 px. An input under 16 px makes iOS Safari zoom the page. |
| ux-33 | Nothing scrolls sideways or is cut off. | No horizontal page scroll. Tables and code blocks reflow or scroll inside their own box. No clipped labels or buttons. |
| ux-34 | Nothing depends on hover. | Tooltips, menus, and actions that appear on hover have a tap equivalent. |
| ux-35 | System areas don't cover content. | The notch, status bar, home indicator, and gesture area leave controls clear. |
| ux-36 | Fixed bars leave room for the content. | Add up the sticky header, cookie bar, chat bubble, and app banner. If they cover more than about a quarter of the screen, it's a finding. |
| ux-37 | Larger system text doesn't break the layout. | At a font scale of 1.3 or more (Android) or a large Dynamic Type size (iOS), nothing clips or overlaps. |

## Large screens

| Id | Rule | How to check |
| --- | --- | --- |
| ux-40 | Lines of text are 45 to 75 characters long. | Content doesn't stretch across a 1920 px window. |
| ux-41 | At 1366x768 the heading and main action are visible without scrolling. | The laptop viewport is short. Check it, not only a tall monitor. |
| ux-42 | The keyboard works. | Focus is visible, tab order follows the reading order, and Enter submits the form. |

## Readability

| Id | Rule | How to check |
| --- | --- | --- |
| ux-50 | Text contrast is at least 4.5:1, or 3:1 for large text. Measure. | Large means 24 px and up, or about 19 px and up in bold. Icons and control borders need 3:1. Gray text on a gray background is the usual failure. |
| ux-51 | Color is never the only signal. | An error has an icon and text along with the red. A selected state has more than a color change. |
| ux-52 | Text over an image or gradient stays readable across the whole image. | Check the lightest and busiest part of the image behind the text. |
