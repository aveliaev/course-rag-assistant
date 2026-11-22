"""Loopback HTTP gateway for the KT3 action sandbox and its annotated contract."""

import argparse
import hmac
import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fkn_assistant.config import REPO
from fkn_assistant.evaluation.dataset import snapshot
from fkn_assistant.forms import Sandbox
from fkn_assistant.staff import StaffOffice

MAX_BODY = 16_384


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    profile_id: str = Field(min_length=1, max_length=80)


class Button(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["confirm", "cancel"]
    draft_id: UUID
    revision: int = Field(strict=True, ge=1)
    confirmation: str | None = Field(default=None, max_length=128)


class FormTurn(Request):
    session_id: str = Field(min_length=1, max_length=100)
    text: str = Field(default="", max_length=2000)
    button: Button | None = None


class TicketPreview(Request):
    request_id: str = Field(min_length=1, max_length=100)
    topic: Literal["E1", "E2", "E3", "E4"] = Field(alias="class")
    summary: str = Field(min_length=1, max_length=1000)


class TicketConfirm(Request):
    card_id: UUID
    confirmation: str = Field(min_length=1, max_length=128)


OPERATIONS = {
    "/v1/forms/turn": FormTurn,
    "/v1/staff/preview": TicketPreview,
    "/v1/staff/confirm": TicketConfirm,
}


class Gateway:
    def __init__(self, sandbox, profiles, clock=None):
        self.sandbox = sandbox
        self.office = StaffOffice(sandbox)
        self.profiles = profiles
        self.clock = clock or (lambda: datetime.now(ZoneInfo("Europe/Moscow")))

    def post(self, path, body):
        model = OPERATIONS.get(path)
        if model is None:
            return 404, {"code": "unknown_operation"}
        try:
            request = model.model_validate_json(body)
        except ValidationError:
            return 422, {"code": "invalid_request"}
        profile = self.profiles.get(request.profile_id)
        if not profile or not profile.get("is_synthetic"):
            return 403, {"code": "unknown_synthetic_profile"}
        owner = profile["id"]
        now = self.clock()
        if isinstance(request, TicketPreview):
            return self.office.preview(
                owner, request.request_id, request.topic, request.summary, now
            )
        if isinstance(request, TicketConfirm):
            return self.office.confirm(
                owner, request.card_id, request.confirmation, now
            )
        button = request.button.model_dump(mode="json") if request.button else None
        answer = self.sandbox.handle(
            ("kt3-http", request.session_id, owner),
            profile,
            now,
            request.text,
            button,
        )
        if answer is None:
            return 200, {"status": "no_form"}
        return 200, answer


def handler_for(gateway, token):
    expected = ("Bearer " + token).encode()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(3)
            super().setup()

        def log_message(self, *_):
            pass

        def send_json(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            auth = self.headers.get("Authorization", "").encode()
            if not hmac.compare_digest(auth, expected):
                self.send_json(401, {"code": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BODY:
                self.send_json(422, {"code": "invalid_body_size"})
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json(422, {"code": "invalid_content_type"})
                return
            try:
                status, value = gateway.post(self.path, self.rfile.read(length))
            except psycopg.Error:
                status, value = 503, {"code": "sandbox_unavailable"}
            except TimeoutError:
                status, value = 503, {"code": "request_timeout"}
            self.send_json(status, value)

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="Локальный HTTP-шлюз форм и учебного офиса"
    )
    parser.add_argument("--repo", default=REPO, type=Path)
    parser.add_argument("--port", default=18083, type=int)
    args = parser.parse_args()
    token = os.environ.get("KT3_SANDBOX_TOKEN", "")
    if len(token) < 24:
        parser.error("Задай случайный KT3_SANDBOX_TOKEN длиной не менее 24 символов")
    profiles = {p["id"]: p for p in json.loads(snapshot(args.repo, "students.json"))}
    sandbox = Sandbox()
    try:
        gateway = Gateway(sandbox, profiles)
        with HTTPServer(
            ("127.0.0.1", args.port), handler_for(gateway, token)
        ) as server:
            server.serve_forever()
    finally:
        sandbox.db.close()


if __name__ == "__main__":
    main()
