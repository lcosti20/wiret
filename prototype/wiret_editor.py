#!/usr/bin/env python3
"""Launch the Wiret graph editor:  python3 wiret_editor.py [FILE.wiret]"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wiret.editor import main  # noqa: E402

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
