# Rules for screen readers and keyboards

A screenshot shows none of this. Check each rule against the accessibility tree (what a screen reader announces, in order), the keyboard walk, and the `accessibility` block from `scripts/measure.js`. A rule is broken only when the user described in SKILL.md would be slowed, confused, or stopped. Skip a rule that is broken on paper and harmless on the screen. Cite the id in each finding.

| Id | Rule | How to check |
| --- | --- | --- |
| ux-100 | Every control has a name that says what it does. | In the tree, each button, link, and field has a name in words. An icon button with no name is announced as "button". A name of "×" or "⋮" is a symbol, not a name. |
| ux-101 | Images that carry meaning have alt text that says what they show. Decorative images are hidden. | "Chart: revenue up 20% since March" passes. "image", "chart.png", or a missing alt fails. Decoration has an empty alt so it isn't read out. |
| ux-102 | Headings outline the page. | Screen reader users jump from heading to heading. Read the heading list alone: one h1 that names the page, no skipped levels, and text that looks like a heading is marked up as one. |
| ux-103 | The page has landmarks and a way past the navigation. | One main region and a named navigation. On pages with a long header, the first Tab stop is a "Skip to content" link. |
| ux-104 | The tree reads in the order the eye does. | Read the tree top to bottom. Content that appears out of order, twice, or in the middle of something else is a finding. Text that was moved with CSS often reads in the old order. |
| ux-105 | Fields are tied to their labels, hints, and errors. | The tree gives each field its label as its name, and required fields are marked. After a failed submit the error is in the tree next to its field, and the field is marked invalid. |
| ux-106 | State is announced. | A menu button says expanded or collapsed. A tab, option, or toggle says selected, checked, or pressed. The current page is marked in the navigation. Custom widgets built from plain boxes usually say nothing. |
| ux-107 | Changes are announced. | Take the tree before and after an action. A toast, an inline error, new search results, or a finished load must reach the user: focus moves to it, or it sits in a live region. A change that appears only visually didn't happen for this user. |
| ux-108 | Everything works with the keyboard alone. | Walk each task with Tab, Enter, Space, Escape, and the arrow keys. Every control is reachable, the order follows the layout, and nothing traps focus. A clickable box that never gets focus fails. So does a `tabindex` above 0, which reorders the page. |
| ux-109 | Focus is always visible and never hidden. | In the keyboard walk's screenshots, each stop shows a clear ring or change. Focus under a sticky header or cookie bar counts as hidden. |
| ux-110 | Dialogs and menus manage focus. | Opening one moves focus into it. Tab stays inside. Escape closes it. Focus goes back to the control that opened it. |
| ux-111 | Link and button names make sense on their own. | Screen reader users pull up a list of all links. Six links named "Learn more" fail. "Learn more about pricing" passes. |
| ux-112 | The page has a title and a language. | The title names the screen and changes when the screen changes, in single-page apps too. The language is set, or the screen reader reads the text with the wrong accent. |
| ux-113 | Zoom works. | Pinch zoom isn't disabled. At 200% zoom, or at a 320 px wide viewport, the content reflows into one column with nothing lost. |
| ux-114 | Motion can be stopped. | Nothing flashes. Autoplaying video, carousels, and looping animation can be paused, and reduced-motion settings are respected. |
| ux-115 | Audio and video have text. | Videos have captions. Audio-only content has a transcript. |
| ux-116 | Native apps label for TalkBack and VoiceOver. | Every tappable node has text or a content description. A row made of several views is read as one item. Any swipe or drag action also has a button. |
