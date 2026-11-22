"""Validation of the calibrated search configuration."""

import ast
import json
from hashlib import sha256

from fkn_assistant.config import PACKAGE
from fkn_assistant.index import MANIFEST


def search_fingerprint() -> str:
    retrieval_symbols = {
        "PERIOD",
        "COURSE",
        "period_for",
        "eq",
        "Search",
        "terms",
        "sparse",
    }
    retrieval_nodes = []
    for filename in ("rag.py", "index.py"):
        for node in ast.parse((PACKAGE / filename).read_text()).body:
            if isinstance(node, ast.Assign):
                names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            else:
                names = {getattr(node, "name", None)}
            if names & retrieval_symbols:
                retrieval_nodes.append(ast.dump(node, include_attributes=False))
    return sha256("\n".join(retrieval_nodes).encode()).hexdigest()


def calibration() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    data = json.loads(MANIFEST.with_name("retrieval.json").read_text())
    if (
        data["collection"] != manifest["collection"]
        or data["search_code"] != search_fingerprint()
    ):
        raise ValueError("Повтори калибровку на smoke текущей версии поиска")
    return data
