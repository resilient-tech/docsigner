"""Finder's "Open With", on macOS only.

Windows and Linux hand the paths over as command-line arguments, which
`startup.remember` already reads. macOS does not: a bundled app is launched with
no arguments and then *sent* an "open documents" Apple event, so without this the
app would appear in Finder's Open With menu and then open empty.

Nothing here runs on any other platform, and every failure is swallowed: an app
that will not start is far worse than one that ignores an Open With.
"""

import logging
import sys
from urllib.parse import unquote, urlparse

from . import startup

log = logging.getLogger(__name__)

# 'aevt'/'odoc' — the open-documents Apple event — and '----', the keyword its
# file list arrives under. Four-character codes, as big-endian ints.
_CLASS = int.from_bytes(b"aevt", "big")
_ID = int.from_bytes(b"odoc", "big")
_DIRECT = int.from_bytes(b"----", "big")
_FILE_URL = int.from_bytes(b"furl", "big")

_handler = None  # module-level: the event manager keeps no strong reference


def install(on_files=None) -> None:
    """Start listening. `on_files` is called after each event, once paths are in.

    Call after the window exists: AppKit installs its own handler for this event
    while the app finishes launching, and the last one registered wins.
    """
    if sys.platform != "darwin":
        return
    global _handler
    try:
        import objc
        from Foundation import NSAppleEventManager, NSObject

        class _OpenDocs(NSObject):
            def handleEvent_withReplyEvent_(self, event, _reply):
                try:
                    paths = _paths_in(event, _FILE_URL)
                    if not paths:
                        return
                    # Extend rather than replace: several events can arrive for
                    # one drop, and the launch case may already have set some.
                    startup.remember(startup.PATHS + paths)
                    if on_files:
                        on_files(paths)
                except Exception:  # noqa: BLE001 - never take the app down
                    log.exception("could not read an Open With event")

        _handler = _OpenDocs.alloc().init()
        NSAppleEventManager.sharedAppleEventManager().setEventHandler_andSelector_forEventClass_andEventID_(
            _handler, objc.selector(b"handleEvent:withReplyEvent:"), _CLASS, _ID
        )
        log.info("listening for Open With")
    except Exception:  # noqa: BLE001 - pyobjc missing, or AppKit said no
        log.exception("Open With is not available")


def _paths_in(event, file_url_type) -> list[str]:
    """The dropped files, as plain paths.

    The list arrives as aliases or bookmarks depending on how Finder was asked,
    so each item is coerced to a file:// URL first — the one form that is always
    available and always means the same thing.
    """
    items = event.paramDescriptorForKeyword_(_DIRECT)
    if items is None:
        return []
    out = []
    for i in range(1, items.numberOfItems() + 1):  # Apple events count from 1
        url = items.descriptorAtIndex_(i).coerceToDescriptorType_(file_url_type)
        if url is None:
            continue
        text = url.stringValue()
        if text:
            out.append(unquote(urlparse(text).path))
    return out
