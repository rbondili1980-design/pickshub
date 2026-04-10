"""Add the backend/ directory to sys.path so scrapers/ is importable."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
