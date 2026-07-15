import sys


def configure_utf8_stdio() -> None:
    """Keep Vietnamese console output from crashing on legacy Windows code pages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (OSError, ValueError):
            # Redirected/captured streams may reject reconfiguration but already
            # accept Unicode text, so there is nothing else to do here.
            pass
