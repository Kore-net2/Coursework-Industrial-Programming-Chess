"""Portable Tk paths for Windows Python distributions and frozen builds."""
import os
from pathlib import Path
import sys


def configure_tk():
    if os.name != "nt":
        return
    # Tcl can mishandle absolute Windows paths in redirected user directories.
    # Relative paths avoid that problem; no global machine settings are changed.
    for variable, folder in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):
        path = Path(os.environ.get(variable, str(Path(sys.base_prefix) / "tcl" / folder)))
        if path.is_dir():
            try:
                os.environ[variable] = os.path.relpath(path)
            except ValueError:  # Different drive: retain the existing absolute path.
                os.environ[variable] = str(path)
