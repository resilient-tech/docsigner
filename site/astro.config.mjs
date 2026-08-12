import { defineConfig } from 'astro/config';
import icon from 'astro-icon';

// The canonical origin lives here and nowhere else. `Astro.site` reads it, so
// canonical tags, og:url and the sitemap all follow one edit. Buying the real
// domain is phase 0 in docs/website.md; until then this is the Pages hostname.
export default defineConfig({
  site: 'https://docsigner.pages.dev',
  output: 'static',
  integrations: [icon({ include: { lucide: ['*'] } })],
  build: {
    // One <style> per page instead of a request for a 2 KB stylesheet. The site
    // has no shared-cache story worth the extra round trip.
    inlineStylesheets: 'always',
  },

  vite: {
    // The stylesheet entry imports design/, which sits above this project root.
    // The build resolves it either way; the dev server refuses without this.
    server: { fs: { allow: ['..'] } },
    build: {
      // Astro inlines small component <script> bundles into the HTML, and the
      // CSP in public/_headers sets script-src 'self' with no 'unsafe-inline',
      // so an inlined bundle gets blocked in production while dev keeps working
      // (the dev server doesn't send _headers). 0 forces every script to a file.
      assetsInlineLimit: 0,
    },
  },

  // The CSP is a real header, set in public/_headers. Not a <meta> tag: meta
  // delivery silently ignores frame-ancestors, and a header can vary per path,
  // which is what /demo will need for Pyodide's wasm.
  //
  // Astro's experimental.csp was the obvious fit and emitted nothing at all on
  // a static build here, so it isn't used.
  devToolbar: { enabled: false },
});
