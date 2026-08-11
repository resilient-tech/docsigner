# Bundled fonts

All licensed under the SIL Open Font License 1.1. `LICENSE-OFL.txt` carries the
full text and every copyright holder.

Handwriting scripts (`appearance.font` values in CONTRACTS.md). Five hands, one
per signing personality, so choosing is a glance rather than a scroll:

- `great-vibes` — GreatVibes-Regular.ttf, (c) 2010 The Great Vibes Pro Project Authors (default; calligraphy)
- `caveat` — Caveat-Regular.ttf, (c) 2014 The Caveat Project Authors (casual)
- `nanum-pen-script` — NanumPenScript-Regular.ttf, (c) 2010 NHN Corporation (pen)
- `cookie` — Cookie-Regular.ttf, (c) 2011 Ania Kruk (brush)
- `bad-script` — BadScript-Regular.ttf, (c) 2011 The Bad Script Project Authors (neat script)

Detail lines:

- Poppins-Regular.ttf — (c) 2020 The Poppins Project Authors

Want another hand? Nothing has to change here: `appearance.register_fonts(dir)`
adds any `.ttf`/`.otf` under a directory the calling app owns, keyed by
filename. The desktop app exposes that as an upload.
