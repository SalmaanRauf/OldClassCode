"""Local Kimi/OpenCode compatibility proxy for Protiviti Atlas MS Foundry.

OpenCode's OpenAI-compatible provider can emit fields that some Atlas
deployments reject. This proxy keeps OpenCode pointed at localhost, rewrites
the small set of incompatible fields, and forwards the request to Atlas with
headers taken from environment variables.

Do not put secrets in this file. Set them in the shell that starts the proxy.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlencode

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


app = FastAPI(title="Atlas Kimi OpenCode Proxy", version="1.0.0")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool_env(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _atlas_key() -> str:
    return _env("ATLAS_API_KEY") or _env("ATLAS_MSF_SUBSCRIPTION_KEY")


def _base_url() -> str:
    return _env("ATLAS_BASE_URL", "https://dev.atlas.protiviti.com/msf").rstrip("/")


def _api_version() -> str:
    return _env("ATLAS_API_VERSION", "")


def _upstream_style() -> str:
    return _env("ATLAS_UPSTREAM_STYLE", "openai-v1").lower()


def _token_parameter() -> str:
    return _env("ATLAS_TOKEN_PARAMETER", "max_tokens").lower()


def _include_api_version(style: str) -> bool:
    default = style != "openai-v1"
    return _bool_env("ATLAS_INCLUDE_API_VERSION", default)


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _rewrite_body(body: dict[str, Any], model: str | None) -> dict[str, Any]:
    rewritten = dict(body)

    token_parameter = _token_parameter()
    if token_parameter not in {"max_tokens", "max_completion_tokens", "strip"}:
        raise ValueError(
            "ATLAS_TOKEN_PARAMETER must be one of: max_tokens, "
            "max_completion_tokens, strip"
        )

    if token_parameter == "max_completion_tokens":
        if "max_tokens" in rewritten and "max_completion_tokens" not in rewritten:
            rewritten["max_completion_tokens"] = rewritten.pop("max_tokens")
        else:
            rewritten.pop("max_tokens", None)
    elif token_parameter == "max_tokens":
        if "max_completion_tokens" in rewritten and "max_tokens" not in rewritten:
            rewritten["max_tokens"] = rewritten.pop("max_completion_tokens")
        else:
            rewritten.pop("max_completion_tokens", None)
    else:
        rewritten.pop("max_tokens", None)
        rewritten.pop("max_completion_tokens", None)

    # Atlas has rejected this AI SDK/OpenCode field on existing deployments.
    rewritten.pop("reasoningSummary", None)

    for field_name in _split_csv(_env("ATLAS_STRIP_PARAMS")):
        rewritten.pop(field_name, None)

    # Body-routed Foundry endpoints need model in the JSON payload.
    if model and _upstream_style() in {"openai-v1", "models"}:
        rewritten.setdefault("model", model)

    return rewritten


def _target_url(model: str | None, incoming_query: dict[str, str]) -> str:
    style = _upstream_style()
    base = _base_url()

    if style == "deployments":
        if not model:
            raise ValueError("deployment style requires a model/deployment name")
        path = f"/openai/deployments/{model}/chat/completions"
    elif style == "openai-v1":
        path = "/openai/v1/chat/completions"
    elif style == "models":
        path = "/models/chat/completions"
    else:
        raise ValueError(
            "ATLAS_UPSTREAM_STYLE must be one of: deployments, openai-v1, models"
        )

    query = dict(incoming_query)
    if _include_api_version(style):
        query["api-version"] = query.get("api-version") or _api_version()
    else:
        query.pop("api-version", None)

    qs = f"?{urlencode(query)}" if query else ""
    return f"{base}{path}{qs}"


def _atlas_headers(request: Request) -> dict[str, str]:
    key = _atlas_key()
    headers: dict[str, str] = {
        "content-type": "application/json",
        "accept": request.headers.get("accept", "application/json"),
    }

    if key:
        headers["api-key"] = key
        subscription_header = _env("ATLAS_SUBSCRIPTION_HEADER", "MSF-Subscription-Key")
        if subscription_header:
            headers[subscription_header] = key
        if _bool_env("ATLAS_SEND_OCP_APIM_HEADER", True):
            headers["Ocp-Apim-Subscription-Key"] = key
        for header_name in _split_csv(_env("ATLAS_ADDITIONAL_SUBSCRIPTION_HEADERS")):
            headers[header_name] = key

    auth_type = _env("ATLAS_AUTH_TYPE") or request.headers.get("AtlasAuthType", "")
    if auth_type:
        headers["AtlasAuthType"] = auth_type

    if _upstream_style() == "models":
        extra_parameters = _env("ATLAS_EXTRA_PARAMETERS", "pass-through")
    else:
        extra_parameters = _env("ATLAS_EXTRA_PARAMETERS")
    if extra_parameters:
        headers["extra-parameters"] = extra_parameters

    entra_token = _env("ATLAS_ENTRA_TOKEN")
    if entra_token:
        headers["Authorization"] = f"Bearer {entra_token}"
    elif _bool_env("ATLAS_FORWARD_AUTHORIZATION", False):
        inbound_auth = request.headers.get("authorization")
        if inbound_auth:
            headers["Authorization"] = inbound_auth

    return headers


async def _forward_chat(request: Request, model: str | None) -> Response:
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": "JSON request body must be an object"},
                status_code=400,
            )

        request_model = model or payload.get("model")
        rewritten = _rewrite_body(payload, request_model)
        target = _target_url(request_model, dict(request.query_params))
        headers = _atlas_headers(request)

        timeout = httpx.Timeout(
            connect=float(_env("ATLAS_CONNECT_TIMEOUT", "30")),
            read=float(_env("ATLAS_READ_TIMEOUT", "300")),
            write=float(_env("ATLAS_WRITE_TIMEOUT", "60")),
            pool=float(_env("ATLAS_POOL_TIMEOUT", "30")),
        )

        stream = bool(rewritten.get("stream"))
        client = httpx.AsyncClient(timeout=timeout)

        if stream:
            upstream = client.build_request(
                "POST",
                target,
                headers=headers,
                json=rewritten,
            )
            response = await client.send(upstream, stream=True)

            async def body_iter():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()

            return StreamingResponse(
                body_iter(),
                status_code=response.status_code,
                media_type=response.headers.get("content-type", "text/event-stream"),
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower()
                    in {
                        "cache-control",
                        "x-request-id",
                        "apim-request-id",
                    }
                },
            )

        async with client:
            response = await client.post(target, headers=headers, json=rewritten)
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/json"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except httpx.RequestError as exc:
        return JSONResponse(
            {
                "error": "Atlas upstream request failed",
                "detail": str(exc),
            },
            status_code=502,
        )


@app.get("/health")
async def health() -> dict[str, Any]:
    style = _upstream_style()
    return {
        "ok": True,
        "base_url": _base_url(),
        "api_version": _api_version(),
        "include_api_version": _include_api_version(style),
        "upstream_style": style,
        "token_parameter": _token_parameter(),
        "strip_params": _split_csv(_env("ATLAS_STRIP_PARAMS")),
        "subscription_header": _env("ATLAS_SUBSCRIPTION_HEADER", "MSF-Subscription-Key"),
        "auth_type": _env("ATLAS_AUTH_TYPE"),
        "extra_parameters": (
            _env("ATLAS_EXTRA_PARAMETERS", "pass-through")
            if style == "models"
            else _env("ATLAS_EXTRA_PARAMETERS")
        ),
        "has_api_key": bool(_atlas_key()),
        "has_entra_token": bool(_env("ATLAS_ENTRA_TOKEN")),
    }


@app.post("/openai/deployments/{deployment}/chat/completions")
async def deployment_chat(deployment: str, request: Request) -> Response:
    return await _forward_chat(request, deployment)


@app.post("/openai/v1/chat/completions")
async def openai_v1_chat(request: Request) -> Response:
    return await _forward_chat(request, None)


@app.post("/v1/chat/completions")
async def v1_chat(request: Request) -> Response:
    return await _forward_chat(request, None)


@app.post("/models/chat/completions")
async def models_chat(request: Request) -> Response:
    return await _forward_chat(request, None)


if __name__ == "__main__":
    uvicorn.run(
        "atlas_kimi_opencode_proxy:app",
        host=_env("ATLAS_PROXY_HOST", "127.0.0.1"),
        port=int(_env("ATLAS_PROXY_PORT", "8011")),
        reload=False,
        log_level=_env("ATLAS_PROXY_LOG_LEVEL", "info"),
    )
