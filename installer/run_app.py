"""PyInstaller entry-point script. A .spec file's Analysis needs an actual
script path, not a module import string, so this is a thin wrapper around
ponn_punch_press.app.main()."""
import sys

from ponn_punch_press.app import main

if __name__ == "__main__":
    sys.exit(main())
