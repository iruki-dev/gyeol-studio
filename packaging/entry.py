"""Entry point of the frozen app (PyInstaller).  freeze_support must run first so worker processes start correctly."""

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from gyeol_studio.launcher import main

    sys.exit(main())
