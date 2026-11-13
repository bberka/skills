// Measures what a screenshot can't show reliably: tap target sizes, text sizes,
// contrast, clipped text, sideways overflow, unlabeled fields, how much of the
// viewport fixed bars cover, and what a screen reader or keyboard user would
// run into (the `accessibility` block).
//
// Run it inside the page at each viewport, after the page has settled. The whole
// file is one expression that evaluates to a JSON-friendly object:
//
//   Playwright:      await page.evaluate(fs.readFileSync('measure.js', 'utf8'))
//   Any browser tool with an "evaluate script" action: pass the file's text
//   DevTools console: paste it
//
// Every item carries a selector and the element's position. Look at the same
// spot in the screenshot before reporting it: an item hidden behind a closed
// menu or covered by another layer is not a finding.
(() => {
  const MAX_ITEMS = 40;
  // Not innerWidth: on a phone, content wider than the screen stretches
  // innerWidth to fit it, which would hide the overflow being looked for.
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;

  const selectorOf = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    const parts = [];
    for (let node = el; node && node.nodeType === 1 && parts.length < 4; node = node.parentElement) {
      let part = node.localName;
      const classes = [...node.classList].slice(0, 2).map((c) => `.${CSS.escape(c)}`).join('');
      part += classes;
      const siblings = node.parentElement
        ? [...node.parentElement.children].filter((s) => s.localName === node.localName)
        : [];
      if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      parts.unshift(part);
      if (node.id) {
        parts[0] = `#${CSS.escape(node.id)}`;
        break;
      }
    }
    return parts.join(' > ');
  };

  const textOf = (el) =>
    (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 60);

  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    const style = getComputedStyle(el);
    if (style.visibility !== 'visible' || style.display === 'none') return false;
    for (let node = el; node; node = node.parentElement) {
      if (parseFloat(getComputedStyle(node).opacity) === 0) return false;
    }
    return true;
  };

  const describe = (el, extra) => {
    const rect = el.getBoundingClientRect();
    return {
      selector: selectorOf(el),
      text: textOf(el),
      x: Math.round(rect.left + window.scrollX),
      y: Math.round(rect.top + window.scrollY),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      inFirstViewport: rect.top + window.scrollY < vh,
      ...extra,
    };
  };

  const all = [...document.querySelectorAll('body *')].filter(isVisible);

  // --- Tap targets -----------------------------------------------------------
  const interactiveSelector =
    'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], ' +
    '[role=tab], [role=menuitem], [role=checkbox], [role=radio], [role=switch], [onclick], [tabindex]:not([tabindex="-1"])';
  const interactive = all.filter((el) => el.matches(interactiveSelector));

  // A small checkbox or radio inside a label is fine when the label is the target.
  const tapRect = (el) => {
    const label = el.matches('input[type=checkbox], input[type=radio]') ? el.closest('label') || el.labels?.[0] : null;
    return (label || el).getBoundingClientRect();
  };
  // A link inside a sentence is exempt from the size rule (WCAG 2.5.8, inline).
  const isInlineLink = (el) =>
    el.localName === 'a' &&
    getComputedStyle(el).display.startsWith('inline') &&
    [...el.parentElement.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 0);

  const tapTargets = [];
  for (const el of interactive) {
    if (isInlineLink(el)) continue;
    const rect = tapRect(el);
    const small = Math.min(rect.width, rect.height);
    if (small >= 44) continue;
    tapTargets.push(
      describe(el, {
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        level: small < 24 ? 'below 24px floor' : 'below 44px',
      }),
    );
  }

  // --- Text size -------------------------------------------------------------
  const ownText = (el) =>
    [...el.childNodes]
      .filter((n) => n.nodeType === 3)
      .map((n) => n.textContent)
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim();
  const textElements = all.filter((el) => ownText(el).length > 1);

  const smallText = [];
  for (const el of textElements) {
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size < 12) smallText.push(describe(el, { text: ownText(el).slice(0, 60), fontSize: size }));
  }

  const zoomingInputs = all
    .filter((el) => el.matches('input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea'))
    .filter((el) => parseFloat(getComputedStyle(el).fontSize) < 16)
    .map((el) => describe(el, { fontSize: parseFloat(getComputedStyle(el).fontSize) }));

  // The size most of the running text is set in.
  const sizeWeights = new Map();
  for (const el of textElements) {
    const text = ownText(el);
    if (text.length < 40) continue;
    const size = parseFloat(getComputedStyle(el).fontSize);
    sizeWeights.set(size, (sizeWeights.get(size) || 0) + text.length);
  }
  const bodyFontSize = [...sizeWeights.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;

  // --- Contrast --------------------------------------------------------------
  const parseColor = (value) => {
    const match = value.match(/rgba?\(([^)]+)\)/);
    if (!match) return null;
    const parts = match[1].split(/[\s,/]+/).filter(Boolean).map(Number);
    if (parts.length < 3 || parts.some(Number.isNaN)) return null;
    return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] ?? 1 };
  };
  const blend = (top, bottom) => ({
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
    a: 1,
  });
  const luminance = ({ r, g, b }) => {
    const channel = (v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
  };
  const ratio = (a, b) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  // Stack the background colors from the element up to the root. Returns null
  // when an image or gradient is involved, because then the color can't be known.
  const backgroundOf = (el) => {
    const layers = [];
    for (let node = el; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage !== 'none') return null;
      const color = parseColor(style.backgroundColor);
      if (!color) return null;
      if (color.a > 0) layers.push(color);
      if (color.a === 1) break;
    }
    let result = { r: 255, g: 255, b: 255, a: 1 };
    for (const layer of layers.reverse()) result = blend(layer, result);
    return result;
  };

  const lowContrast = [];
  const unknownContrast = [];
  for (const el of textElements) {
    const style = getComputedStyle(el);
    const color = parseColor(style.color);
    if (!color) continue;
    const background = backgroundOf(el);
    if (!background) {
      unknownContrast.push(describe(el, { text: ownText(el).slice(0, 60), reason: 'text over an image or gradient' }));
      continue;
    }
    const size = parseFloat(style.fontSize);
    const bold = parseInt(style.fontWeight, 10) >= 700;
    const large = size >= 24 || (bold && size >= 18.66);
    const needed = large ? 3 : 4.5;
    const actual = ratio(blend(color, background), background);
    if (actual < needed) {
      lowContrast.push(
        describe(el, {
          text: ownText(el).slice(0, 60),
          ratio: Math.round(actual * 100) / 100,
          needed,
          color: style.color,
          fontSize: size,
        }),
      );
    }
  }

  // --- Clipped text ----------------------------------------------------------
  const clippedText = [];
  for (const el of textElements) {
    const style = getComputedStyle(el);
    const hidesX = style.overflowX !== 'visible' && style.overflowX !== 'auto' && style.overflowX !== 'scroll';
    const hidesY = style.overflowY !== 'visible' && style.overflowY !== 'auto' && style.overflowY !== 'scroll';
    const cutX = hidesX && el.scrollWidth > el.clientWidth + 1;
    const cutY = hidesY && el.scrollHeight > el.clientHeight + 1;
    if (cutX || cutY) {
      clippedText.push(describe(el, { text: ownText(el).slice(0, 60), fullText: (el.textContent || '').trim().slice(0, 160) }));
    }
  }

  // --- Sideways overflow -----------------------------------------------------
  const pageWidth = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  const overflowsSideways = pageWidth > vw + 1;
  const insideScroller = (el) => {
    for (let node = el.parentElement; node && node !== document.body; node = node.parentElement) {
      const overflowX = getComputedStyle(node).overflowX;
      if (overflowX === 'auto' || overflowX === 'scroll' || overflowX === 'hidden' || overflowX === 'clip') return true;
    }
    return false;
  };
  const wideElements = overflowsSideways
    ? all
        .filter((el) => el.getBoundingClientRect().right > vw + 1 && !insideScroller(el))
        .filter((el) => getComputedStyle(el).position !== 'fixed') // fixed bars stretch because of the overflow, they don't cause it
        .filter((el, _, list) => !list.some((other) => other !== el && el.contains(other)))
        .map((el) => describe(el, { overflowBy: Math.round(el.getBoundingClientRect().right - vw) }))
    : [];

  // --- Fields without a visible label ----------------------------------------
  const unlabeledFields = all
    .filter((el) => el.matches('input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=image]), select, textarea'))
    .filter((el) => {
      const labelled =
        (el.labels && [...el.labels].some(isVisible)) ||
        (el.getAttribute('aria-labelledby') || '')
          .split(/\s+/)
          .some((id) => id && document.getElementById(id) && isVisible(document.getElementById(id)));
      return !labelled;
    })
    .map((el) =>
      describe(el, {
        placeholder: el.getAttribute('placeholder') || '',
        ariaLabel: el.getAttribute('aria-label') || '',
      }),
    );

  // --- Fixed and sticky bars -------------------------------------------------
  // Measured against what is on screen, which on a phone is wider than the
  // layout width when the page overflows and the browser zooms out to fit.
  const screenW = Math.max(vw, window.innerWidth);
  const screenH = Math.max(vh, window.innerHeight);
  const fixed = all.filter((el) => {
    const position = getComputedStyle(el).position;
    if (position !== 'fixed' && position !== 'sticky') return false;
    const rect = el.getBoundingClientRect();
    return rect.bottom > 0 && rect.top < screenH && rect.right > 0 && rect.left < screenW;
  });
  const outermostFixed = fixed.filter((el) => !fixed.some((other) => other !== el && other.contains(el)));
  let coveredArea = 0;
  const fixedBars = outermostFixed.map((el) => {
    const rect = el.getBoundingClientRect();
    const width = Math.max(0, Math.min(rect.right, screenW) - Math.max(rect.left, 0));
    const height = Math.max(0, Math.min(rect.bottom, screenH) - Math.max(rect.top, 0));
    coveredArea += width * height;
    return describe(el, {
      position: getComputedStyle(el).position,
      coversPercent: Math.round((width * height * 100) / (screenW * screenH)),
    });
  });

  const cap = (list) => ({ count: list.length, items: list.slice(0, MAX_ITEMS) });

  // --- Screen readers and keyboards ------------------------------------------
  // An approximation of the accessible name: what a screen reader would say for
  // the element. Text hidden with aria-hidden or display:none isn't spoken.
  const spokenText = (el) => {
    let out = '';
    const walk = (node) => {
      if (node.nodeType === 3) {
        out += node.textContent;
        return;
      }
      if (node.nodeType !== 1 || node.getAttribute('aria-hidden') === 'true') return;
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden') return;
      if (node !== el && node.getAttribute('aria-label')) out += ` ${node.getAttribute('aria-label')} `;
      else if (node.localName === 'img') out += ` ${node.getAttribute('alt') || ''} `;
      else for (const child of node.childNodes) walk(child);
    };
    walk(el);
    return out.replace(/\s+/g, ' ').trim();
  };
  const nameOf = (el) => {
    const referenced = (el.getAttribute('aria-labelledby') || '')
      .split(/\s+/)
      .map((id) => (id && document.getElementById(id)?.textContent) || '')
      .join(' ')
      .trim();
    if (referenced) return referenced;
    const ariaLabel = (el.getAttribute('aria-label') || '').trim();
    if (ariaLabel) return ariaLabel;
    const labels = el.labels ? [...el.labels].map((label) => spokenText(label)).join(' ').trim() : '';
    if (labels) return labels;
    if (el.matches('input[type=submit], input[type=button], input[type=reset]')) return el.value || el.type;
    if (el.matches('img, input[type=image]')) return (el.getAttribute('alt') || '').trim();
    if (!el.matches('input, select, textarea')) {
      const text = spokenText(el);
      if (text) return text;
    }
    return (el.getAttribute('title') || '').trim();
  };
  const hasWords = (text) => /[\p{L}\p{N}]/u.test(text);

  const unnamedControls = [];
  for (const el of interactive) {
    const name = nameOf(el);
    if (hasWords(name)) continue;
    const placeholder = el.getAttribute('placeholder') || '';
    unnamedControls.push(
      describe(el, {
        announcedAs: name || placeholder || '(nothing)',
        problem: placeholder ? 'placeholder is the only name' : name ? 'name is a symbol, not words' : 'no name',
      }),
    );
  }

  const isDecorative = (el) =>
    el.closest('[aria-hidden=true]') || ['presentation', 'none'].includes(el.getAttribute('role'));
  const imagesWithoutAlt = [];
  for (const el of all) {
    if (isDecorative(el)) continue;
    if (el.localName === 'img') {
      const alt = el.getAttribute('alt');
      if (alt === null) imagesWithoutAlt.push(describe(el, { problem: 'no alt attribute', src: (el.currentSrc || '').slice(-60) }));
      else if (/\.(png|jpe?g|gif|svg|webp|avif)$/i.test(alt) || /^(image|photo|picture|img|icon|logo|graphic)$/i.test(alt.trim()))
        imagesWithoutAlt.push(describe(el, { problem: 'alt says nothing', alt }));
    } else if (el.getAttribute('role') === 'img' && !hasWords(nameOf(el))) {
      imagesWithoutAlt.push(describe(el, { problem: 'role=img with no name' }));
    }
  }

  const headingEls = all.filter((el) => el.matches('h1, h2, h3, h4, h5, h6, [role=heading]'));
  const headings = headingEls.map((el) => ({
    level: Number(el.getAttribute('aria-level')) || Number(el.localName[1]) || 2,
    text: spokenText(el).slice(0, 80),
  }));
  const headingProblems = [];
  const h1Count = headings.filter((h) => h.level === 1).length;
  if (headings.length === 0) headingProblems.push('no headings: a screen reader user has nothing to jump between');
  else if (h1Count === 0) headingProblems.push('no h1');
  if (h1Count > 1) headingProblems.push(`${h1Count} h1 headings`);
  headings.forEach((h, i) => {
    if (i > 0 && h.level > headings[i - 1].level + 1)
      headingProblems.push(`level jumps from h${headings[i - 1].level} to h${h.level} at "${h.text}"`);
    if (!hasWords(h.text)) headingProblems.push(`empty h${h.level}`);
  });

  const vagueNames = /^(click here|here|read more|learn more|more|more info|details|link|this|go|view|see more|continue)$/i;
  const linkNames = new Map();
  for (const el of interactive.filter((e) => e.matches('a[href], [role=link]'))) {
    const name = nameOf(el).toLowerCase();
    if (!hasWords(name)) continue;
    const entry = linkNames.get(name) || { name, targets: new Set() };
    entry.targets.add(el.getAttribute('href') || '');
    linkNames.set(name, entry);
  }
  const vagueLinks = [...linkNames.values()]
    .filter((entry) => vagueNames.test(entry.name) || entry.targets.size > 1)
    .map((entry) => ({
      name: entry.name,
      differentTargets: entry.targets.size,
      problem: vagueNames.test(entry.name) ? 'says nothing out of context' : 'same name, different destinations',
    }));

  // Things that respond to a click but can't be reached with the Tab key.
  const notKeyboardReachable = [];
  for (const el of all) {
    if (el.matches('label, label *') || el.closest('[aria-hidden=true]')) continue;
    if (el.matches('[role=button], [role=link], [role=checkbox], [role=switch]')) {
      if (el.tabIndex < 0 && !el.hasAttribute('tabindex') && !el.closest('a[href], button'))
        notKeyboardReachable.push(describe(el, { problem: `role=${el.getAttribute('role')} without tabindex` }));
      continue;
    }
    if (el.matches(interactiveSelector) || el.closest(interactiveSelector) || el.querySelector(interactiveSelector)) continue;
    if (getComputedStyle(el).cursor !== 'pointer') continue;
    if (el.parentElement && getComputedStyle(el.parentElement).cursor === 'pointer') continue;
    notKeyboardReachable.push(describe(el, { problem: 'looks clickable (pointer cursor) but is not a control' }));
  }

  const positiveTabindex = all.filter((el) => el.tabIndex > 0).map((el) => describe(el, { tabindex: el.tabIndex }));
  const focusableInsideHidden = all
    .filter((el) => el.tabIndex >= 0 && el.matches(interactiveSelector) && el.closest('[aria-hidden=true]'))
    .map((el) => describe(el, { problem: 'focusable but hidden from screen readers' }));

  const viewportMeta = document.querySelector('meta[name=viewport]')?.getAttribute('content') || '';
  const maxScale = parseFloat((viewportMeta.match(/maximum-scale\s*=\s*([\d.]+)/) || [])[1]);
  const zoomBlocked = /user-scalable\s*=\s*(no|0)/.test(viewportMeta) || maxScale < 2;

  const accessibility = {
    language: document.documentElement.getAttribute('lang') || null, // ux-112
    title: document.title || null, // ux-112
    zoomBlocked, // ux-113
    landmarks: {
      main: document.querySelectorAll('main, [role=main]').length,
      nav: document.querySelectorAll('nav, [role=navigation]').length,
    }, // ux-103
    headings: headings.slice(0, 60), // ux-102, read these alone: do they outline the page?
    headingProblems,
    unnamedControls: cap(unnamedControls), // ux-100
    imagesWithoutAlt: cap(imagesWithoutAlt), // ux-101
    vagueLinks: cap(vagueLinks), // ux-111
    notKeyboardReachable: cap(notKeyboardReachable), // ux-108
    positiveTabindex: cap(positiveTabindex), // ux-108
    focusableInsideHidden: cap(focusableInsideHidden), // ux-108
    autoplayingMedia: document.querySelectorAll('video[autoplay], audio[autoplay]').length, // ux-114
  };

  return {
    url: location.href,
    viewport: { width: vw, height: vh, devicePixelRatio: window.devicePixelRatio },
    pageHeight: document.documentElement.scrollHeight,
    bodyFontSize,
    interactiveCount: interactive.length,
    tapTargets: cap(tapTargets), // ux-30
    smallText: cap(smallText), // ux-32, text under 12px
    zoomingInputs: cap(zoomingInputs), // ux-32, inputs under 16px zoom on iOS Safari
    lowContrast: cap(lowContrast), // ux-50
    unknownContrast: cap(unknownContrast), // ux-52, check these by eye
    clippedText: cap(clippedText), // ux-33
    overflowsSideways, // ux-33
    wideElements: cap(wideElements),
    unlabeledFields: cap(unlabeledFields), // ux-21
    fixedBars: { coversPercent: Math.min(100, Math.round((coveredArea * 100) / (screenW * screenH))), items: fixedBars.slice(0, MAX_ITEMS) }, // ux-36
    accessibility,
  };
})()
