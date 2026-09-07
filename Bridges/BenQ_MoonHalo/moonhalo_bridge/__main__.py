"""Allows `py -m moonhalo_bridge ...` to run the command-line mode."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
