import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import httpx
import openai

from fkn_assistant.model_client import (
    ApiError,
    Completion,
    Deadline,
    GenerationOptions,
    Message,
)

MODEL = "GigaChat-3-Ultra"
OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT = "https://api.giga.chat/v1/chat/completions"
OPTIONS: GenerationOptions = {
    "model": MODEL,
    "temperature": 0.1,
    "stream": False,
    "function_call": "none",
    "max_tokens": 700,
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GigaChat:
    def __init__(self, env_file, ca_file):
        key = os.environ.get("GIGACHAT_CREDENTIALS")
        if not key and env_file.is_file():
            for line in env_file.read_text().splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "GIGACHAT_CREDENTIALS":
                    key = value.strip().strip("'\x22")
                    break
        if not key:
            raise SystemExit("Укажи GIGACHAT_CREDENTIALS в окружении или .env.")
        self.key = key
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(ca_file))
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context), NoRedirect()
        )
        self.http = httpx.Client(verify=context, follow_redirects=False)
        self.access_token = None
        self.sdk = None
        self.expires = 0

    def post(self, stage, url, data, authorization, content_type, timeout):
        headers = {
            "Authorization": authorization,
            "Content-Type": content_type,
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
        }
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self.opener.open(req, timeout=timeout) as response:
                return json.load(response), response.headers.get("X-Request-ID")
        except urllib.error.HTTPError as exc:
            raise ApiError(stage, exc.code, exc.headers.get("X-Request-ID")) from None
        except (OSError, ValueError, ssl.SSLError) as exc:
            raise ApiError(stage, type(exc).__name__) from None

    def authenticate(self, deadline: Deadline) -> None:
        if time.time() + 60 < self.expires:
            return
        data = urllib.parse.urlencode({"scope": "GIGACHAT_API_PERS"}).encode()
        result, request_id = self.post(
            "oauth",
            OAUTH,
            data,
            "Basic " + self.key,
            "application/x-www-form-urlencoded",
            deadline.remaining("oauth", 15),
        )
        try:
            token = result["access_token"]
            expires = float(result["expires_at"])
            if not isinstance(token, str) or not token:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ApiError("oauth", "invalid_provider_response", request_id) from None
        self.access_token = token
        self.expires = expires / 1000 if expires > 10_000_000_000 else expires
        if self.sdk is None:
            self.sdk = openai.OpenAI(
                api_key=lambda: self.access_token,
                base_url=CHAT.removesuffix("/chat/completions"),
                http_client=self.http,
                max_retries=0,
            )

    def close(self) -> None:
        self.http.close()

    def count_tokens(
        self, model: str, pieces: list[str], deadline: Deadline
    ) -> list[int]:
        self.authenticate(deadline)
        response, request_id = self.post(
            "tokens",
            CHAT.removesuffix("/chat/completions") + "/tokens/count",
            json.dumps({"model": model, "input": pieces}).encode(),
            "Bearer " + self.access_token,
            "application/json",
            deadline.remaining("tokens", 3),
        )
        try:
            counts = [row["tokens"] for row in response]
            if len(counts) != len(pieces) or any(
                type(n) is not int or n < 0 for n in counts
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ApiError("tokens", "invalid_provider_response", request_id) from None
        deadline.remaining("tokens", 3)
        return counts

    def generate(
        self,
        messages: list[Message],
        options: GenerationOptions,
        deadline: Deadline,
        *,
        timeout: float,
    ) -> Completion:
        self.authenticate(deadline)
        try:
            response = self.sdk.chat.completions.with_raw_response.create(
                model=options["model"],
                messages=messages,
                temperature=options["temperature"],
                max_tokens=options["max_tokens"],
                stream=False,
                extra_body={"function_call": options["function_call"]},
                extra_headers={"RqUID": str(uuid.uuid4())},
                timeout=deadline.remaining("chat", timeout),
            )
        except openai.APIStatusError as exc:
            raise ApiError("chat", exc.status_code, exc.request_id) from None
        except openai.APITimeoutError:
            raise ApiError("chat", "timeout") from None
        except openai.APIConnectionError:
            raise ApiError("chat", "connection_error") from None
        except openai.APIError:
            raise ApiError("chat", "invalid_provider_response") from None
        request_id = response.headers.get("X-Request-ID")
        try:
            data = response.parse()
            choice = data.choices[0]
            usage = data.usage.model_dump(
                include={"prompt_tokens", "completion_tokens", "total_tokens"}
            )
            if not isinstance(choice.message.content, str) or not isinstance(
                data.model, str
            ):
                raise ValueError
            cached_tokens = getattr(data.usage, "precached_prompt_tokens", None)
            if len(usage) != 3 or any(
                type(n) is not int or n < 0 for n in usage.values()
            ):
                raise ValueError
        except (AttributeError, IndexError, TypeError, ValueError):
            raise ApiError("chat", "invalid_provider_response", request_id) from None
        if type(cached_tokens) is int and cached_tokens >= 0:
            usage["precached_prompt_tokens"] = cached_tokens
        deadline.remaining("chat", 45)
        return Completion(
            choice.message.content, data.model, usage, choice.finish_reason, request_id
        )
