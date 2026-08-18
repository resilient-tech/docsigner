/*
 * The theme switch, in one place.
 *
 * Two things call it: the nav's toggle, and the theme button inside the desktop
 * app prototype -- that button exists in the real app, so making it work in the
 * mock is honest as well as fun.
 *
 * "paper" is the canonical name for the light scheme; design/tokens.css also
 * matches data-theme="light" so anything stored by an older build still resolves.
 */

export const isPaper = () => document.documentElement.dataset.theme === 'paper';

export function setTheme(paper: boolean) {
  if (paper) document.documentElement.dataset.theme = 'paper';
  else delete document.documentElement.dataset.theme;
  try {
    localStorage.setItem('theme', paper ? 'paper' : 'dark');
  } catch {
    /* Private mode. The choice still holds for this page. */
  }
  document.dispatchEvent(new CustomEvent('themechange'));
}

export const toggleTheme = () => setTheme(!isPaper());
