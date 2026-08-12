/*
 * Sets the theme before first paint, so there is no flash of the wrong one.
 *
 * A file rather than an inline <script> so that `script-src 'self'` covers it
 * with no 'unsafe-inline' and no hash to keep in step with the source. It is
 * loaded blocking in <head>: nothing paints until head is parsed, and this is
 * about 300 bytes from the same origin.
 *
 * Dark is the default. A stored choice beats the OS, and the OS beats the
 * default, same order the desktop app uses.
 *
 * The light scheme is called PAPER. design/tokens.css matches both
 * data-theme="paper" and data-theme="light", so a value stored by an older
 * build still resolves; this writes the canonical name.
 */
(() => {
  let stored = null;
  try {
    stored = localStorage.getItem('theme');
  } catch {
    /* Private mode, or storage denied. Fall through to the OS preference. */
  }
  const paper =
    stored === 'paper' ||
    stored === 'light' ||
    (stored === null && matchMedia('(prefers-color-scheme: light)').matches);
  if (paper) document.documentElement.dataset.theme = 'paper';
})();
