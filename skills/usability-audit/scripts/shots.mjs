#!/usr/bin/env node
// Captures one web page on each device: screenshots cut into screen-sized tiles,
// measure.js results, and the accessibility tree.
//
//   node shots.mjs <url> <name> [--out <dir>] [--devices phone,tablet,desktop,wide]
//                               [--dark] [--storage <state.json>] [--wait <ms>]
//
// Writes, per device, into <out>/<device>/ :
//   <name>-01.png, -02.png ...  the page top to bottom, one screen per tile (01 is
//                               what the user sees before scrolling)
//   <name>-full.png             the whole page, for the report
//   <name>-measure.json         output of measure.js
//   <name>-tree.yml             the accessibility tree
// and prints a JSON summary. Run it from a directory where `playwright` is installed.
//
// For a task with several steps, import the helpers instead of using the CLI:
//
//   import { openDevice, captureStep } from '<this file>';
//   const { page, close } = await openDevice('phone');
//   await page.goto('http://localhost:3000');
//   await captureStep(page, 'out/web-phone-360/signup-01-home');
//   await page.getByRole('link', { name: 'Sign up' }).click();
//   await captureStep(page, 'out/web-phone-360/signup-02-form');
//   await close();

import { createRequire } from 'node:module';
import { mkdirSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const MAX_TILES = 12;

// Scale factors are kept low on purpose. A tile much over 1500 px on its long
// side gets shrunk when a model reads it, and small text stops being legible.
export const DEVICES = {
  phone: { dir: 'web-phone-360', viewport: { width: 360, height: 800 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  tablet: { dir: 'web-tablet-820', viewport: { width: 820, height: 1180 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true },
  desktop: { dir: 'web-desktop-1366', viewport: { width: 1366, height: 768 } },
  wide: { dir: 'web-desktop-1920', viewport: { width: 1920, height: 1080 } },
};

function loadPlaywright() {
  for (const from of [pathToFileURL(join(process.cwd(), 'x')), import.meta.url]) {
    try {
      return createRequire(from)('playwright');
    } catch {
      // try the next place
    }
  }
  console.error(
    'Playwright was not found from the current directory.\n' +
      'Run this from a folder that has it, or make one:\n' +
      '  mkdir -p /tmp/ua-playwright && cd /tmp/ua-playwright && npm init -y && npm i playwright && npx playwright install chromium',
  );
  process.exit(2);
}

/** Opens a browser page set up as one of DEVICES. Returns { page, context, device, close }. */
export async function openDevice(deviceName, { dark = false, storage } = {}) {
  const device = DEVICES[deviceName];
  if (!device) throw new Error(`Unknown device "${deviceName}". Use one of: ${Object.keys(DEVICES).join(', ')}`);
  const { chromium } = loadPlaywright();
  const browser = await chromium.launch();
  const { dir, ...options } = device;
  const context = await browser.newContext({
    ...options,
    colorScheme: dark ? 'dark' : 'light',
    ...(storage ? { storageState: storage } : {}),
  });
  const page = await context.newPage();
  return { page, context, device, close: () => browser.close() };
}

/** Captures the page's current state to <outBase>-NN.png, -full.png, -measure.json, -tree.yml. */
export async function captureStep(page, outBase) {
  mkdirSync(dirname(resolve(outBase)), { recursive: true });
  await page.evaluate(() => document.fonts.ready);

  // Scroll through once so lazy-loaded content is there, then return to where we were.
  const size = await page.evaluate(async () => {
    const start = window.scrollY;
    const step = document.documentElement.clientHeight;
    for (let y = 0; y < document.documentElement.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((done) => setTimeout(done, 80));
    }
    window.scrollTo(0, start);
    await new Promise((done) => setTimeout(done, 150));
    return {
      width: document.documentElement.clientWidth,
      height: document.documentElement.clientHeight,
      pageHeight: document.documentElement.scrollHeight,
    };
  });

  // Tiles are real scroll positions, so sticky headers and fixed bars sit where the
  // user sees them. Each one overlaps the last a little so nothing falls in a seam.
  const tiles = [];
  const step = Math.round(size.height * 0.85);
  const lastScroll = Math.max(0, size.pageHeight - size.height);
  const count = Math.min(MAX_TILES, 1 + Math.ceil(lastScroll / step));
  const startScroll = await page.evaluate(() => window.scrollY);
  for (let i = 0; i < count; i++) {
    const path = `${outBase}-${String(i + 1).padStart(2, '0')}.png`;
    if (i > 0) {
      await page.evaluate((y) => window.scrollTo(0, y), startScroll + Math.min(i * step, lastScroll));
      await page.waitForTimeout(150);
    }
    await page.screenshot({ path });
    tiles.push(path);
  }
  await page.evaluate((y) => window.scrollTo(0, y), startScroll);
  await page.screenshot({ path: `${outBase}-full.png`, fullPage: true });

  const measure = await page.evaluate(readFileSync(join(here, 'measure.js'), 'utf8'));
  writeFileSync(`${outBase}-measure.json`, JSON.stringify(measure, null, 2));
  writeFileSync(`${outBase}-tree.yml`, await page.locator('body').ariaSnapshot());

  const a = measure.accessibility;
  return {
    tiles,
    tilesCutOffAt: (count - 1) * step < lastScroll ? `${MAX_TILES} screens` : null,
    measure: `${outBase}-measure.json`,
    tree: `${outBase}-tree.yml`,
    counts: {
      tapTargets: measure.tapTargets.count,
      smallText: measure.smallText.count,
      zoomingInputs: measure.zoomingInputs.count,
      lowContrast: measure.lowContrast.count,
      clippedText: measure.clippedText.count,
      overflowsSideways: measure.overflowsSideways,
      unlabeledFields: measure.unlabeledFields.count,
      fixedBarsCoverPercent: measure.fixedBars.coversPercent,
      unnamedControls: a.unnamedControls.count,
      imagesWithoutAlt: a.imagesWithoutAlt.count,
      notKeyboardReachable: a.notKeyboardReachable.count,
      headingProblems: a.headingProblems.length,
    },
  };
}

export function parseArgs(argv, flagsWithValue) {
  const positional = [];
  const flags = {};
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--')) positional.push(arg);
    else if (flagsWithValue.includes(arg.slice(2))) flags[arg.slice(2)] = argv[++i];
    else flags[arg.slice(2)] = true;
  }
  return { positional, flags };
}

async function main() {
  const { positional, flags } = parseArgs(process.argv.slice(2), ['out', 'devices', 'storage', 'wait']);
  const [url, name] = positional;
  if (!url || !name) {
    console.error('Usage: node shots.mjs <url> <name> [--out <dir>] [--devices phone,tablet,desktop,wide] [--dark] [--storage <state.json>] [--wait <ms>]');
    process.exit(2);
  }
  const out = flags.out || 'shots';
  const summary = {};
  for (const deviceName of (flags.devices || 'phone,desktop').split(',')) {
    const { page, device, close } = await openDevice(deviceName.trim(), { dark: Boolean(flags.dark), storage: flags.storage });
    try {
      await page.goto(url, { waitUntil: 'networkidle' });
      if (flags.wait) await page.waitForTimeout(Number(flags.wait));
      const dir = flags.dark ? `${device.dir}-dark` : device.dir;
      summary[dir] = await captureStep(page, join(out, dir, name));
    } finally {
      await close();
    }
  }
  console.log(JSON.stringify(summary, null, 2));
}

if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) {
  await main();
}
