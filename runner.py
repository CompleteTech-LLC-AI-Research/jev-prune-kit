"""Absolute-path entry point: the installer embeds this path, not a PATH alias."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jev_prune.worker import main as worker
from jev_prune.cli import main as cli
raise SystemExit(worker() if sys.argv[1:] == ["--worker"] else cli())
