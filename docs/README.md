# DocSigner docs

Start with [architecture.md](architecture.md). It's the picture the rest hangs off.

## How this is organised

Three layers. Each fact has one home, so there's nothing to keep in sync.

| Layer | Where | What's in it |
|---|---|---|
| Door | [`../README.md`](../README.md) | What it is, run it in 5 minutes |
| Concept | `docs/*.md` (here) | Plain words, a diagram, a module map |
| Commands | `<module>/README.md` | Build, install, deploy, quirks |

Each concept page splits at a `---`. Above it, anyone can read. Below it, the
commands and code for whoever works on that module.

## Pages

**Understanding it**

- [architecture.md](architecture.md) — how all the pieces fit, and why
- [core.md](core.md) — `docsigner-core`, the signing engine
- [server.md](server.md) — `docsigner-server`, the HTTP layer
- [host.md](host.md) — `docsigner-host`, the piece that reaches the token
- [desktop.md](desktop.md) — `docsigner-desktop`, the local batch app

The browser side (extension + `docsigner.js`) is small enough to live in its own
folder: [`../extension/README.md`](../extension/README.md) and
[`../js/README.md`](../js/README.md).

**The contract**

- [`../CONTRACTS.md`](../CONTRACTS.md) — every wire format, frozen. HTTP routes,
  native messaging commands, the page bridge, error codes.

**Planning**

- [roadmap.md](roadmap.md) — what's left to build here
- [release-checklist.md](release-checklist.md) — manual runs before a release merge
- [frappe-app.md](frappe-app.md) — the Frappe integration's plan (different repo)

## Adding a doc

Ask which layer the fact belongs to, then write it there and only there. If it
already lives somewhere, link instead of copying.

Module maps are checked by `core/tests/test_docs.py`: add a source file, forget
its doc line, and the test suite says so.
