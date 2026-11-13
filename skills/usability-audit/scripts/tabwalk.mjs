#!/usr/bin/env node
// Presses Tab through a web page and records where focus lands. Finds controls
// the keyboard can't reach, focus that can't be seen, focus that goes off screen,
// an order that jumps around, and focus traps.
//
//   node tabwalk.mjs <url> <name> [--out <dir>] [--max <stops>] [--storage <state.json>]
//
// Writes into <out>/keyboard/ :
//   <name>-stops.json     every stop, the controls never reached, and a summary
//   <name>-NN.png         a screenshot at each stop
// and prints the summary. Open only the screenshots the summary points to.
// Run it from a directory where `playwright` is installed.

import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { openDevice, parseArgs } from './shots.mjs';

const { positional, flags } = parseArgs(process.argv.slice(2), ['out', 'max', 'storage']);
const [url, name] = positional;
if (!url || !name) {
  console.error('Usage: node tabwalk.mjs <url> <name> [--out <dir>] [--max <stops>] [--storage <state.json>]');
  process.exit(2);
}
const dir = join(flags.out || 'shots', 'keyboard');
const max = Number(flags.max || 60);
mkdirSync(dir, { recursive: true });

const { page, close } = await openDevice('desktop', { storage: flags.storage });
await page.goto(url, { waitUntil: 'networkidle' });
await page.evaluate(() => {
  window.__look = (el) => {
    const s = getComputedStyle(el);
    return [s.outlineStyle, s.outlineWidth, s.outlineColor, s.boxShadow, s.borderColor, s.backgroundColor, s.color, s.textDecorationLine].join('|');
  };
});

const stops = [];
let wrapped = false;
for (let i = 1; i <= max; i++) {
  await page.keyboard.press('Tab');
  const stop = await page.evaluate((i) => {
    const el = document.activeElement;
    if (!el || el === document.body) return null;
    if (el.dataset.tabStop) return 'seen';
    el.dataset.tabStop = i;
    const r = el.getBoundingClientRect();
    let pinned = false;
    for (let node = el; node; node = node.parentElement) {
      const position = getComputedStyle(node).position;
      if (position === 'fixed' || position === 'sticky') pinned = true;
    }
    return {
      stop: i,
      tag: el.localName,
      text: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').replace(/\s+/g, ' ').trim().slice(0, 50),
      x: Math.round(r.left + scrollX),
      y: Math.round(r.top + scrollY),
      fixed: pinned,
      onScreen: r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth && r.width > 0,
      focused: window.__look(el),
    };
  }, i);
  if (!stop || stop === 'seen') {
    wrapped = true; // back at the start: the whole page has been walked
    break;
  }
  stop.screenshot = join(dir, `${name}-${String(i).padStart(2, '0')}.png`);
  await page.screenshot({ path: stop.screenshot });
  stops.push(stop);
}

// A stop that looks the same with and without focus has no visible focus.
await page.evaluate(() => document.activeElement?.blur());
for (const stop of stops) {
  const resting = await page.evaluate((i) => window.__look(document.querySelector(`[data-tab-stop="${i}"]`)), stop.stop);
  stop.focusVisible = resting !== stop.focused;
  delete stop.focused;
}

// Visible controls that Tab never landed on.
const neverReached = wrapped
  ? await page.evaluate(() => {
      const selector =
        'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], ' +
        '[role=checkbox], [role=switch], [role=tab], [role=menuitem], [onclick]';
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility === 'visible' && s.display !== 'none';
      };
      const groupVisited = (el) =>
        el.type === 'radio' && el.name && [...document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)].some((r) => r.dataset.tabStop);
      return [...document.querySelectorAll(selector)]
        .filter((el) => visible(el) && !el.dataset.tabStop && !el.disabled && !groupVisited(el))
        .map((el) => {
          const r = el.getBoundingClientRect();
          return {
            tag: el.localName,
            id: el.id || null,
            text: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').replace(/\s+/g, ' ').trim().slice(0, 50),
            x: Math.round(r.left + scrollX),
            y: Math.round(r.top + scrollY),
            note:
              el.getAttribute('tabindex') === '-1'
                ? 'tabindex=-1: fine inside tabs, menus, and toolbars that move with arrow keys, a bug elsewhere'
                : 'not focusable',
          };
        });
    })
  : [];

// Stops that send focus back up the page by more than a screen-third. Fixed bars are skipped.
const orderJumps = [];
const flow = stops.filter((s) => !s.fixed);
for (let i = 1; i < flow.length; i++) {
  if (flow[i].y < flow[i - 1].y - 250) orderJumps.push({ from: flow[i - 1].stop, to: flow[i].stop, text: flow[i].text });
}

const summary = {
  stops: stops.length,
  wrapped,
  possibleTrapOrEndlessList: !wrapped,
  noVisibleFocus: stops.filter((s) => !s.focusVisible).map((s) => ({ stop: s.stop, text: s.text, screenshot: s.screenshot })),
  focusOffScreen: stops.filter((s) => !s.onScreen).map((s) => ({ stop: s.stop, text: s.text, screenshot: s.screenshot })),
  orderJumps,
  neverReached,
};
const file = join(dir, `${name}-stops.json`);
writeFileSync(file, JSON.stringify({ summary, stops }, null, 2));
console.log(JSON.stringify({ file, ...summary }, null, 2));
await close();
