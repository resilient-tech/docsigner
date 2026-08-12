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
 */
(() => {
  let stored = null;
  try {
    stored = localStorage.getItem('theme');
  } catch {
    /* Private mode, or storage denied. Fall through to the OS preference. */
  }
  const light =
    stored === 'light' ||
    (stored === null && matchMedia('(prefers-color-scheme: light)').matches);
  if (light) document.documentElement.dataset.theme = 'light';
})();
