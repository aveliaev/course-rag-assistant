"""Validation of the calibrated search configuration."""

import json

from fkn_assistant.config import PACKAGE
from fkn_assistant.index import MANIFEST, checksum


def search_fingerprint() -> str:
    return checksum(PACKAGE / "rag.py")


def calibration() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    data = json.loads(MANIFEST.with_name("retrieval.json").read_text())
    if (
        data["collection"] != manifest["collection"]
        or data["search_code"] != search_fingerprint()
    ):
        raise ValueError("Повтори калибровку на smoke текущей версии поиска")
    return data
