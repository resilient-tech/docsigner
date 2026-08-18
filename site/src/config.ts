/*
 * Every outbound URL, one place.
 *
 * The repo is private and the extension is in neither store (roadmap D1), so
 * some of these don't resolve yet. `ready: false` marks those, and components
 * render them as a stated fact instead of a dead link. Going public, or getting
 * a store ID, is an edit here and nothing else.
 */

export const REPO = 'https://github.com/resilient-tech/docsigner';

/**
 * Everything ships together, so the repo-derived links are live: docs, source,
 * issues, releases, the licence.
 *
 * The extension stores are NOT covered by this. Store review takes weeks after
 * submission and there are no listing URLs to link to yet, so `stores` stays
 * unready and /download offers the release zips until those come through.
 */
export const REPO_PUBLIC = true;

export const links = {
  repo: REPO,
  issues: `${REPO}/issues`,
  releases: `${REPO}/releases`,
  releaseLatest: `${REPO}/releases/latest`,
  license: `${REPO}/blob/HEAD/LICENSE`,
  notice: `${REPO}/blob/HEAD/NOTICE`,
  security: `${REPO}/security/policy`,
  contracts: `${REPO}/blob/HEAD/CONTRACTS.md`,

  /* Docs stay in the repo. No port, nothing to keep in sync.
     `HEAD` resolves to the default branch, so these survive a branch rename
     the way a named branch does not. core/tests/test_docs.py checks each
     path is still a file in the repo. */
  docs: `${REPO}/blob/HEAD/docs/README.md`,
  docsArchitecture: `${REPO}/blob/HEAD/docs/architecture.md`,
  docsCore: `${REPO}/blob/HEAD/docs/core.md`,
  docsServer: `${REPO}/blob/HEAD/docs/server.md`,
  docsHost: `${REPO}/blob/HEAD/docs/host.md`,
  docsDesktop: `${REPO}/blob/HEAD/docs/desktop.md`,
  docsExtension: `${REPO}/blob/HEAD/extension/README.md`,
  docsJs: `${REPO}/blob/HEAD/js/README.md`,
  roadmap: `${REPO}/blob/HEAD/docs/roadmap.md`,

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

/**
 * Whether the Windows binaries are code-signed. Independent of REPO_PUBLIC on
 * purpose: the free SignPath certificate is a third-party review that takes its
 * own weeks, and until it lands SmartScreen says "Unknown publisher". A signing
 * product should be the first to tell you that, not the last, so /download warns
 * while this is false. One flip when the certificate arrives.
 */
export const WINDOWS_SIGNED = false;

/** Homebrew tap. Ships with the release. */
export const brew = {
  ready: true,
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
  '/why': true,
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
