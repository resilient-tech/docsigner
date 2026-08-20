/*
 * Comparison switch, temporary scaffolding: see components/ToneSwitch.astro.
 *
 * Runs before paint, like theme.js, so the chosen tone is on the element from
 * the first frame instead of flashing the shipped one first. A ?tone= parameter
 * wins over the stored choice and becomes the stored choice.
 *
 * Keep TONES in step with ToneSwitch's options. It is an allowlist rather than a
 * pass-through so a stale or hand-typed value cannot put the site in a state
 * with no way back to the shipped one.
 */
(function () {
  var TONES = ['flat', 'rule', 'objects', 'tick', 'measure', 'numbers', 'gutter'];
  var param = new URLSearchParams(location.search).get('tone');
  var tone = param || localStorage.getItem('tone') || '';
  if (TONES.indexOf(tone) !== -1) document.documentElement.dataset.tone = tone;
  if (param) localStorage.setItem('tone', TONES.indexOf(param) !== -1 ? param : '');
})();
