"""Paths and context shared by the runtime and its entry points."""

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
BASE = PACKAGE.parents[1]
REPO = BASE.parent
RESOURCES = PACKAGE / "resources"
CACHE = BASE / ".cache"

PROFILE_CONTEXT = (
    "educational_program",
    "faculty",
    "campus",
    "level",
    "course",
    "admission_year",
    "status",
)
