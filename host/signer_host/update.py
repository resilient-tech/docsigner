"""Update check: compare the running version against a published one.

A version-check only, no self-download. Native hosts installed by hand go
stale silently and there is no store to push a new build; this lets a page
tell the user a newer host exists and point them at the installer.

The source is a JSON URL, `OPENSIGNER_UPDATE_URL` (falls back to the module
default, empty until a release feed exists), returning at least:

    {"version": "0.2.0", "url": "https://.../download"}

Network and parse failures are soft: they come back as updateAvailable=false
with a message, never as a protocol error, so a check never breaks the page.
"""

import json
import os
import re
import urllib.request

from . import __version__

ENV_URL = "OPENSIGNER_UPDATE_URL"
DEFAULT_UPDATE_URL = ""  # set when a release feed exists
TIMEOUT_SECONDS = 5


def _version_tuple(text):
    return tuple(int(n) for n in re.findall(r"\d+", text or ""))


def _is_newer(latest, current):
    a, b = _version_tuple(latest), _version_tuple(current)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return a > b


def _fetch(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def check_update():
    """Return the current/latest versions and whether an update is available."""
    result = {"currentVersion": __version__, "latestVersion": None,
              "updateAvailable": False, "downloadUrl": None, "message": ""}
    url = os.environ.get(ENV_URL) or DEFAULT_UPDATE_URL
    if not url:
        result["message"] = "no update source configured"
        return result
    try:
        data = _fetch(url)
    except Exception as exc:  # network, HTTP, JSON: all soft failures
        result["message"] = "could not check for updates: %s" % (exc,)
        return result
    latest = str(data.get("version") or "")
    result["latestVersion"] = latest or None
    result["downloadUrl"] = data.get("url")
    if latest and _is_newer(latest, __version__):
        result["updateAvailable"] = True
        result["message"] = "version %s is available" % latest
    else:
        result["message"] = "up to date"
    return result
