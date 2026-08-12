/*
 * Every outbound URL, one place.
 *
 * The repo is private and the extension is in neither store (roadmap D1), so
 * some of these don't resolve yet. `ready: false` marks those, and components
 * render them as a stated fact instead of a dead link. Going public, or getting
 * a store ID, is an edit here and nothing else.
 */

export const REPO = 'https://github.com/resilient-tech/docsigner';

/** Set to true the day the repo goes public. Gates every repo-derived link. */
export const REPO_PUBLIC = false;

export const links = {
  repo: REPO,
  issues: `${REPO}/issues`,
  releases: `${REPO}/releases`,
  releaseLatest: `${REPO}/releases/latest`,
  license: `${REPO}/blob/master/LICENSE`,
  notice: `${REPO}/blob/master/NOTICE`,
  security: `${REPO}/security/policy`,
  contracts: `${REPO}/blob/master/CONTRACTS.md`,

  /* Docs stay in the repo. No port, nothing to keep in sync. */
  docs: `${REPO}/blob/master/docs/README.md`,
  docsArchitecture: `${REPO}/blob/master/docs/architecture.md`,
  docsCore: `${REPO}/blob/master/docs/core.md`,
  docsServer: `${REPO}/blob/master/docs/server.md`,
  docsHost: `${REPO}/blob/master/docs/host.md`,
  docsDesktop: `${REPO}/blob/master/docs/desktop.md`,
  docsExtension: `${REPO}/blob/master/extension/README.md`,
  docsJs: `${REPO}/blob/master/js/README.md`,
  roadmap: `${REPO}/blob/master/docs/roadmap.md`,

  /* The feed every release publishes. Also what the host's checkUpdate reads,
     so the site and the product agree by construction. */
  latestJson: `${REPO}/releases/latest/download/latest.json`,
  checksums: `${REPO}/releases/latest/download/SHA256SUMS`,
  releasesApi: 'https://api.github.com/repos/resilient-tech/docsigner/releases/latest',

  org: 'https://github.com/resilient-tech',
  company: 'https://resilient.tech',
  contact: 'mailto:security@resilient.tech',
} as const;

/**
 * Extension store listings. Unsubmitted, both of them (roadmap D1). Native
 * messaging draws extra review scrutiny, so these land weeks after submission.
 * Until then /setup offers the release zip and load-unpacked instructions.
 */
export const stores = {
  chrome: { url: '', ready: false, label: 'Chrome Web Store' },
  edge: { url: '', ready: false, label: 'Edge Add-ons' },
  firefox: { url: '', ready: false, label: 'Firefox Add-ons' },
} as const;

/** Homebrew tap. Waits on the repo going public, same as the tap repo (D6). */
export const brew = {
  ready: false,
  tap: 'resilient-tech/tap',
  host: 'brew install resilient-tech/tap/docsigner-host',
  desktop: 'brew install --cask resilient-tech/tap/docsigner',
} as const;

/**
 * Which pages exist. Nav and footer filter on this, so a phase landing is one
 * flag flip instead of edits in three components. Build order is in
 * docs/website.md §6.
 */
export const pages = {
  '/': true,
  '/how-it-works': true,
  '/download': true,
  '/setup': false, // phase 2
  '/verify': false, // phase 3
  '/demo': false, // phase 4
  '/standards': true,
  '/components': false, // phase 5
  '/security': false, // phase 5
  '/compare': false, // phase 5
} as const;

export type Page = keyof typeof pages;

export const ready = (href: string): boolean =>
  !href.startsWith('/') || pages[href as Page] === true;

export const site = {
  name: 'DocSigner',
  /* The category in one line, the way the README opens. No slogan. */
  tagline:
    'Open-source digital signatures for PDFs. Sign with a USB token from any website, or with a key on your own server.',
  license: 'Apache-2.0',
  copyrightHolder: 'Resilient Software Services LLP',
  year: 2026,
} as const;
