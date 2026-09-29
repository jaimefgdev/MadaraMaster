#!/usr/bin/env python3
"""Compatibility entry point: ``python madara.py`` is the same as ``madara``."""

from madaramaster.cli import main

if __name__ == "__main__":
    main()
