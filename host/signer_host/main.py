"""Stdio loop for the native messaging host.

Reads framed requests from stdin, writes framed responses to stdout, until EOF.
stdout carries protocol frames only; logging goes to a file under the config
directory, with stderr as the fallback.
"""

import logging
import sys

from . import framing, protocol
from .modules import config_dir


def _setup_logging():
    try:
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(directory / "host.log", encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main():
    _setup_logging()
    log = logging.getLogger(__name__)
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    # A stray print() anywhere must never corrupt protocol frames.
    sys.stdout = sys.stderr

    log.info("host started")
    while True:
        try:
            payload = framing.read_frame(stdin)
        except EOFError:
            log.warning("stream ended mid-frame")
            break
        if payload is None:
            break
        response = protocol.handle_raw(payload)
        try:
            framing.write_message(stdout, response)
        except (BrokenPipeError, OSError):
            log.warning("browser closed the pipe")
            break
        if protocol.restart_requested:
            log.info("exiting after a wedged scan; the extension reconnects on demand")
            break
    log.info("host stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
