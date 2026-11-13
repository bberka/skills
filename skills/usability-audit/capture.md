# Launching the app and capturing it

Read "Safety", the section for each platform in scope, and "Logins and data". Skip the rest.

- [Safety](#safety)
- [Web](#web)
- [Android](#android)
- [iOS](#ios)
- [Flutter, React Native, Expo, Capacitor](#flutter-react-native-expo-capacitor)
- [Desktop apps](#desktop-apps)
- [Browser extensions](#browser-extensions)
- [Logins and data](#logins-and-data)

Find the project's own run commands first, in the README, `package.json` scripts, a Makefile, or `docker-compose.yml`. They beat anything here.

## Safety

- Audit a local or staging build. On a production URL, walk it read-only: no purchases, no deletions, nothing that messages or emails another person.
- Stop at the payment form. Never submit a real payment.
- Use the test account the user gives you, not a real customer's.
- A phone plugged in over USB is the user's own device. Ask before driving it.
- When you finish, stop every server and emulator you started, and reset any device setting you changed.

## Web

Start the app in the background and wait for its port. A production build (`build`, then `preview` or `start`) shows what users get. A dev server is fine when a build is slow, but hide framework overlays and dev toolbars before capturing.

Capture with one of these:

**Your own browser tool** (a browser or preview tool, Playwright or Chrome DevTools over MCP). At each viewport in SKILL.md step 1, take a screenshot per screenful while scrolling down, evaluate `scripts/measure.js` in the page (the file is one expression that returns an object), and take the accessibility snapshot. Turn on touch and a mobile user agent for the phone size, or the site serves its desktop behavior at a narrow width.

**The bundled scripts**, when you have only a shell. They need Node and Playwright. Run them from a folder where `playwright` is installed. If the project doesn't have it, make a scratch folder outside the project (`npm init -y && npm i playwright && npx playwright install chromium`) and run from there.

```bash
# One page on each device. <skill> is the folder that holds SKILL.md.
node <skill>/scripts/shots.mjs <url> <name> --out <report folder>/shots --devices phone,desktop
#   --devices phone,tablet,desktop,wide   default: phone,desktop
#   --dark                                 capture the dark theme (folder gets a -dark suffix)
#   --storage state.json                   reuse a logged-in session
#   --wait 1500                            extra wait in ms for slow pages
```

For each device it writes `<name>-01.png`, `-02.png`, ... (one screenful each, top to bottom, with 01 being what the user sees before scrolling), `<name>-full.png` for the report, `<name>-measure.json`, and `<name>-tree.yml`. It prints the paths and a count of each measured problem, so you can tell which captures need a closer look.

A task with several steps needs a short script of your own. Import the helpers, act, and capture after each step:

```js
import { openDevice, captureStep } from '<skill>/scripts/shots.mjs';

const { page, context, close } = await openDevice('phone'); // phone | tablet | desktop | wide
await page.goto('http://localhost:3000');
await captureStep(page, 'shots/web-phone-360/signup-01-home');
await page.getByRole('link', { name: 'Sign up' }).click();
await captureStep(page, 'shots/web-phone-360/signup-02-form');
await page.getByRole('button', { name: 'Create account' }).click(); // empty submit, to see the errors
await captureStep(page, 'shots/web-phone-360/signup-03-errors');
await context.storageState({ path: 'state.json' }); // after a login, to reuse the session
await close();
```

Notes:

- Let animations finish before a capture, and don't disable them. An animation that holds back content for more than about a second is a finding.
- Emulation doesn't draw the phone's on-screen keyboard. For a form, treat the bottom 40% of the phone viewport as covered and check what is left.

### Keyboard walk

```bash
node <skill>/scripts/tabwalk.mjs <url> <name> --out <report folder>/shots
#   --max 60               stop after this many Tab presses
#   --storage state.json   reuse a logged-in session
```

It presses Tab through the page at 1366x768, takes a screenshot at each stop into `keyboard/`, and prints a summary:

| Field | Meaning |
| --- | --- |
| `neverReached` | Visible controls that Tab never landed on. A keyboard user can't use them. |
| `noVisibleFocus` | Stops that look the same with and without focus. Confirm in the stop's screenshot. |
| `focusOffScreen` | Focus went where the user can't see it: a closed menu, or under a sticky bar. |
| `orderJumps` | Focus moved back up the page. Check whether the order still matches the layout. |
| `possibleTrapOrEndlessList` | Tab never came back to the start within the limit. |

Open only the screenshots the summary names. To finish a task by keyboard, write a script like the one above that uses `page.keyboard.press('Tab')`, `'Enter'`, `'Space'`, `'Escape'`, and the arrow keys in place of clicks. For each dialog and menu, check that focus moves into it, stays in it, and returns when it closes.

## Android

```bash
emulator -list-avds                              # pick a small phone, and a tablet if supported
emulator -avd <name> -no-snapshot-save &         # the binary is in $ANDROID_HOME/emulator
adb wait-for-device
adb shell 'while [ "$(getprop sys.boot_completed)" != 1 ]; do sleep 1; done'

./gradlew installDebug                           # or: flutter run, npx expo run:android, npx react-native run-android
adb shell monkey -p <package> -c android.intent.category.LAUNCHER 1

adb exec-out screencap -p > shot.png             # screenshot
adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml   # what TalkBack reads: text, content-desc, bounds in px
adb shell input tap <x> <y>                      # tap at the center of an element's bounds
adb shell input text 'hello'; adb shell input keyevent KEYCODE_BACK
adb shell wm density                             # px / (density / 160) = dp

adb shell cmd uimode night yes                   # dark mode; "no" to reset
adb shell settings put system font_scale 1.3     # larger text; 1.0 to reset
```

A phone screenshot is often 1080x2400 or larger. Scale it to about 1500 px on the long side before reading it, so the text stays legible.

`ui.xml` is the screen as TalkBack gets it, and it is the accessibility tree for step 6. A node with `clickable="true"` whose `text` and `content-desc` are empty, and whose children have neither, is announced as "button" with no name, or skipped. Nodes are read in file order, so read the file top to bottom to check the reading order.

No AVD exists: creating one needs a system image and several minutes of download. Tell the user what's missing and ask before installing it.

## iOS

Needs macOS with Xcode. On any other system, list iOS under "Not audited".

```bash
xcrun simctl list devices available
xcrun simctl boot "iPhone SE (3rd generation)"   # the smallest current screen
xcrun simctl install booted <path/to/App.app> && xcrun simctl launch booted <bundle id>
xcrun simctl io booted screenshot shot.png
xcrun simctl ui booted appearance dark
xcrun simctl ui booted content_size extra-extra-extra-large
xcrun simctl openurl booted '<deep link>'        # jump to a screen
```

`simctl` can't tap and can't read the accessibility tree. Use the project's own UI test tooling if it has any (Maestro, XCUITest, Detox), or `idb` (`idb ui tap`, and `idb ui describe-all` for the labels VoiceOver reads), or a computer-use tool on the Simulator window. With none of those, capture the screens that deep links reach, and list the rest, and the screen reader pass, under "Not audited".

## Flutter, React Native, Expo, Capacitor

Run on the emulators above. The web build of a cross-platform app renders differently from the native one, so it stands in for the native app only when the web is itself a shipped target.

## Desktop apps

- **Electron:** Playwright drives it: `const app = await _electron.launch({ args: ['.'] }); const page = await app.firstWindow();`. Pass that `page` to `captureStep` from `scripts/shots.mjs`.
- **Tauri and native apps:** launch the dev build and capture the window with a computer-use tool or the OS (`screencapture` on macOS, `grim` or `scrot` on Linux). If the Tauri frontend also runs in a browser from its dev server, audit it there at the window's sizes, and say in the report that native window chrome and menus weren't covered.
- Capture at the default window size and at the smallest size the window allows.

## Browser extensions

Load the unpacked extension in Chromium (`chromium.launchPersistentContext(dir, { args: ['--disable-extensions-except=<path>', '--load-extension=<path>'] })`), read the extension id from its service worker URL, and open `chrome-extension://<id>/popup.html` as a page. A popup sizes itself to its content, up to 800x600, so set the viewport to the popup's real size before calling `captureStep`. Do the same for the options page and any page the extension injects into.

## Logins and data

- Ask for a test account, or look for a seed script (`seed`, `db:seed`, fixtures) and a local `.env.example`.
- Capture a brand-new account and a filled one. Add an item with a very long name and a list long enough to scroll.
- If a screen needs something you can't get, such as a paid plan, a second user, or hardware, list it under "Not audited".
