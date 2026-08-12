/*
 * OS family and browser, from the UA string. Runs in the browser.
 *
 * OS family only. No architecture, no client hints: the release ships one build
 * per operating system ("there is no architecture to choose", in the release
 * notes), so bitness and Rosetta detection would answer a question nobody is
 * asking. The UA string is unreliable for architecture on every engine and
 * perfectly fine for OS family.
 *
 * Both functions return 'unknown' rather than guessing, and every page that
 * uses them shows all downloads as well as the highlighted one.
 */

export type OS = 'macos' | 'windows' | 'linux' | 'unknown';
export type Browser = 'chrome' | 'edge' | 'brave' | 'firefox' | 'safari' | 'unknown';

export function detectOS(ua: string = navigator.userAgent): OS {
  if (/Windows/i.test(ua)) return 'windows';
  /* Order matters: iOS and Android carry 'Linux' and 'Mac' respectively in
     places, and neither has a host build, so they fall through to unknown. */
  if (/Android|iPhone|iPad|iPod/i.test(ua)) return 'unknown';
  if (/Mac OS X|Macintosh/i.test(ua)) return 'macos';
  if (/Linux|X11|CrOS/i.test(ua)) return 'linux';
  return 'unknown';
}

export async function detectBrowser(ua: string = navigator.userAgent): Promise<Browser> {
  /* Brave hides itself in the UA and answers this instead. */
  const brave = (navigator as { brave?: { isBrave?: () => Promise<boolean> } }).brave;
  if (brave?.isBrave) {
    try {
      if (await brave.isBrave()) return 'brave';
    } catch {
      /* Fall through to the UA. */
    }
  }
  if (/Edg\//.test(ua)) return 'edge';
  if (/Firefox\/|FxiOS/.test(ua)) return 'firefox';
  if (/Chrome\/|Chromium\//.test(ua)) return 'chrome';
  if (/Safari\//.test(ua)) return 'safari';
  return 'unknown';
}

export const osLabel: Record<OS, string> = {
  macos: 'macOS',
  windows: 'Windows',
  linux: 'Linux',
  unknown: 'your platform',
};

export const browserLabel: Record<Browser, string> = {
  chrome: 'Chrome',
  edge: 'Edge',
  brave: 'Brave',
  firefox: 'Firefox',
  safari: 'Safari',
  unknown: 'your browser',
};

/**
 * Which extension build a browser takes. Chromium engines share one zip;
 * Firefox has its own. Safari needs a signed macOS app wrapper, which isn't
 * built (docs/architecture.md, "What we skipped, on purpose").
 */
export function extensionFor(browser: Browser): 'chrome' | 'firefox' | null {
  if (browser === 'firefox') return 'firefox';
  if (browser === 'safari' || browser === 'unknown') return null;
  return 'chrome';
}
