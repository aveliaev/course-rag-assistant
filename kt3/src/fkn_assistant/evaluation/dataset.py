"""Versioned dev fixtures and deterministic evaluation sampling."""

import json
import subprocess
from hashlib import sha256

DATA_COMMIT = "6c56bcbcf06f6cba296bb9674a43bf6739887cc0"

FORM_CONTEXT = {
    "temp_pass": ("full_name", "study_group"),
    "enrollment_certificate": (
        "full_name",
        "faculty",
        "educational_program",
        "level",
        "course",
    ),
}


def digest(data):
    return sha256(data).hexdigest()


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def snapshot(repository, filename):
    return subprocess.check_output(
        ["git", "-C", str(repository), "show", f"{DATA_COMMIT}:KT-2/{filename}"]
    )


def fixed_sample(cases, count, minimum_forms=False):
    groups = {}
    for case in cases:
        groups.setdefault(case["category"], []).append(case)
    for group in groups.values():
        group.sort(key=lambda x: digest(x["id"].encode()))
    selected = []
    if minimum_forms:
        for category in FORM_CONTEXT:
            selected.extend(groups.pop(category, []))
    while len(selected) < count:
        for category in sorted(groups):
            if groups[category] and len(selected) < count:
                selected.append(groups[category].pop(0))
        if not any(groups.values()):
            break
    return selected
