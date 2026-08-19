/*
 * Release data, read at build time.
 *
 * `latest.json` is published by .github/workflows/release.yml on every release
 * and is the same feed the host's `checkUpdate` reads, so the site and the
 * product can't disagree about a version. `SHA256SUMS` ships beside it. Sizes
 * come from the releases API, which reports one per asset.
 *
 * Build time, not browser: the download page is static HTML, and a GitHub
 * outage or rate limit can't break a visitor's page load. The cost is that a
 * new release needs a rebuild to appear. Cloudflare Pages has a deploy hook for
 * the release workflow to call.
 *
 * While the repo is private every fetch 404s, so this falls back to the version
 * in host/Cargo.toml and reports `published: false`. Pages then say the release
 * isn't out yet instead of rendering dead links.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { links } from '../config';

export type OS = 'macos' | 'windows' | 'linux';

export interface Artifact {
  /** The key in latest.json's `downloads` map. */
  key: string;
  component: 'host' | 'desktop' | 'extension';
  os: OS | null;
  filename: string;
  url: string;
  size: number | null;
  sha256: string | null;
}

export interface Release {
  version: string;
  /** False while the repo is private: no URLs resolve. */
  published: boolean;
  releaseUrl: string;
  date: string | null;
  artifacts: Artifact[];
}

interface Feed {
  version: string;
  url: string;
  published: string;
  downloads: Record<string, string>;
}

/* The keys latest.json can carry, in the order a human needs them. Labels are
   the page's business; this only says what a key means. */
const KEYS: Record<string, { component: Artifact['component']; os: OS | null }> = {
  'extension-chrome': { component: 'extension', os: null },
  'extension-firefox': { component: 'extension', os: null },
  'host-macos': { component: 'host', os: 'macos' },
  'host-windows': { component: 'host', os: 'windows' },
  'host-linux': { component: 'host', os: 'linux' },
  'desktop-macos': { component: 'desktop', os: 'macos' },
  'desktop-windows': { component: 'desktop', os: 'windows' },
  'desktop-linux': { component: 'desktop', os: 'linux' },
};

/** The release number, from VERSION. Components carry their own; this is the
 *  one the download page shows, because it names the release the files sit in. */
function versionFromSource(): string {
  try {
    /* cwd is site/ during the build, and Pages checks out the whole repo. */
    return readFileSync(join(process.cwd(), '..', 'VERSION'), 'utf8').trim() || '0.0.0';
  } catch {
    return '0.0.0';
  }
}

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { headers: { Accept: 'application/json' } });
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

async function fetchText(url: string): Promise<string | null> {
  try {
    const res = await fetch(url);
    return res.ok ? await res.text() : null;
  } catch {
    return null;
  }
}

/** `<sha256>  <filename>` per line, one file for the whole release. */
function parseChecksums(text: string | null): Map<string, string> {
  const out = new Map<string, string>();
  if (!text) return out;
  for (const line of text.split('\n')) {
    const m = line.trim().match(/^([0-9a-f]{64})\s+\*?(.+)$/i);
    if (m) out.set(m[2].trim(), m[1].toLowerCase());
  }
  return out;
}

let cached: Release | null = null;

export async function getRelease(): Promise<Release> {
  if (cached) return cached;

  const feed = await fetchJson<Feed>(links.latestJson);

  if (!feed?.downloads) {
    cached = {
      version: versionFromSource(),
      published: false,
      releaseUrl: links.releaseLatest,
      date: null,
      artifacts: [],
    };
    return cached;
  }

  const [sums, api] = await Promise.all([
    fetchText(links.checksums),
    fetchJson<{ assets: { name: string; size: number }[] }>(links.releasesApi),
  ]);

  const checksums = parseChecksums(sums);
  const sizes = new Map((api?.assets ?? []).map((a) => [a.name, a.size]));

  const artifacts: Artifact[] = [];
  for (const [key, meta] of Object.entries(KEYS)) {
    const url = feed.downloads[key];
    if (!url) continue; /* A job that didn't run is absent, not a dead link. */
    const filename = url.split('/').pop() ?? key;
    artifacts.push({
      key,
      component: meta.component,
      os: meta.os,
      filename,
      url,
      size: sizes.get(filename) ?? null,
      sha256: checksums.get(filename) ?? null,
    });
  }

  cached = {
    version: feed.version,
    published: true,
    releaseUrl: feed.url || links.releaseLatest,
    date: feed.published ?? null,
    artifacts,
  };
  return cached;
}

export function formatSize(bytes: number | null): string | null {
  if (bytes === null) return null;
  const mb = bytes / 1_048_576;
  return mb < 1 ? `${Math.round(bytes / 1024)} KB` : `${mb.toFixed(1)} MB`;
}
