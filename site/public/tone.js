/*
 * Comparison switch, temporary scaffolding: see components/ToneSwitch.astro.
 *
 * Runs before paint, like theme.js, so the chosen tone is on the element from
 * the first frame instead of flashing the shipped one first. A ?tone= parameter
 * wins over the stored choice and becomes the stored choice.
 */
(function () {
  var param = new URLSearchParams(location.search).get('tone');
  var tone = param || localStorage.getItem('tone') || '';
  if (tone === 'flat' || tone === 'rule') document.documentElement.dataset.tone = tone;
  if (param) localStorage.setItem('tone', tone);
})();
