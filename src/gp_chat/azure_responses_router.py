from __future__ import annotations

from typing import Any, Iterator

from .azure_common_types import AzureRouterResult, AzureStreamChunk, AzureUsageMetadata
from .azure_runtime import AzureRuntime


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _normalize_json_schema(schema: Any) -> Any:
    type_map = {
        "OBJECT": "object",
        "ARRAY": "array",
        "STRING": "string",
        "NUMBER": "number",
        "INTEGER": "integer",
        "BOOLEAN": "boolean",
        "NULL": "null",
    }
    if isinstance(schema, list):
        return [_normalize_json_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    normalized: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            normalized[key] = type_map.get(value.upper(), value.lower())
        else:
            normalized[key] = _normalize_json_schema(value)
    if normalized.get("type") == "object":
        normalized.setdefault("additionalProperties", False)
    return normalized


def _build_text_format(
    *,
    response_mime_type: str | None,
    response_schema: dict[str, Any] | None,
    structured_output_name: str | None,
) -> dict[str, object] | None:
    if response_schema:
        return {
            "format": {
                "type": "json_schema",
                "name": structured_output_name or "structured_output",
                "schema": _normalize_json_schema(response_schema),
                "strict": True,
            }
        }
    if response_mime_type == "application/json":
        return {"format": {"type": "json_object"}}
    return None


def _coerce_usage(raw_usage: Any) -> AzureUsageMetadata | None:
    if raw_usage is None:
        return None
    prompt_tokens = (
        _get_attr(raw_usage, "input_tokens")
        or _get_attr(raw_usage, "prompt_tokens")
        or _get_attr(raw_usage, "prompt_token_count")
        or 0
    )
    output_tokens = (
        _get_attr(raw_usage, "output_tokens")
        or _get_attr(raw_usage, "completion_tokens")
        or _get_attr(raw_usage, "candidates_token_count")
        or 0
    )
    total_tokens = (
        _get_attr(raw_usage, "total_tokens")
        or _get_attr(raw_usage, "total_token_count")
        or (int(prompt_tokens) + int(output_tokens))
    )
    return AzureUsageMetadata(
        prompt_token_count=int(prompt_tokens or 0),
        candidates_token_count=int(output_tokens or 0),
        total_token_count=int(total_tokens or 0),
    )


def normalize_usage(usage_metadata: AzureUsageMetadata | Any) -> dict[str, int | str | None] | None:
    usage = usage_metadata if isinstance(usage_metadata, AzureUsageMetadata) else _coerce_usage(usage_metadata)
    if usage is None:
        return None
    return {
        "prompt_token_count": usage.prompt_token_count,
        "candidates_token_count": usage.candidates_token_count,
        "total_token_count": usage.total_token_count,
        "thoughts_token_count": usage.thoughts_token_count,
        "cached_content_token_count": usage.cached_content_token_count,
        "traffic_type": usage.traffic_type,
    }


def _extract_response_text(response: Any) -> str:
    direct_text = _get_attr(response, "output_text", "") or ""
    if direct_text:
        return direct_text

    text_parts: list[str] = []
    for item in _get_attr(response, "output", []) or []:
        for content in _get_attr(item, "content", []) or []:
            if _get_attr(content, "type") in ("output_text", "text"):
                text_value = _get_attr(content, "text")
                if text_value:
                    text_parts.append(text_value)
    return "".join(text_parts)


def normalize_grounding(response: Any) -> dict[str, object] | None:
    metadata: dict[str, object] = {"sources": [], "queries": []}
    seen_uris: set[str] = set()
    seen_queries: set[str] = set()

    def add_source(uri: str | None, title: str | None = None) -> None:
        if uri and uri not in seen_uris:
            metadata["sources"].append({"title": title or uri, "uri": uri})
            seen_uris.add(uri)

    for item in _get_attr(response, "output", []) or []:
        item_type = _get_attr(item, "type", "")
        if item_type == "web_search_call":
            action = _get_attr(item, "action")
            query = _get_attr(action, "query") or _get_attr(item, "query") or action
            if isinstance(query, str) and query and query not in seen_queries:
                metadata["queries"].append(query)
                seen_queries.add(query)
            for source in _get_attr(action, "sources", []) or []:
                add_source(
                    _get_attr(source, "url") or _get_attr(source, "uri"),
                    _get_attr(source, "title"),
                )
        for content in _get_attr(item, "content", []) or []:
            for annotation in _get_attr(content, "annotations", []) or []:
                if _get_attr(annotation, "type") != "url_citation":
                    continue
                uri = _get_attr(annotation, "url")
                title = _get_attr(annotation, "title")
                if not uri:
                    citation = _get_attr(annotation, "url_citation")
                    uri = _get_attr(citation, "url")
                    title = title or _get_attr(citation, "title")
                add_source(uri, title)

    if not metadata["sources"] and not metadata["queries"]:
        return None
    return metadata


def _build_request_kwargs(
    *,
    runtime: AzureRuntime,
    input_messages: list[dict[str, object]],
    instructions: str,
    max_output_tokens: int,
    temperature: float | None,
    search_enabled: bool,
    response_mime_type: str | None,
    response_schema: dict[str, Any] | None,
    structured_output_name: str | None,
    stream: bool,
) -> dict[str, object]:
    request_kwargs: dict[str, object] = {
        "model": runtime.deployment,
        "input": input_messages,
        "instructions": instructions or None,
        "max_output_tokens": max_output_tokens,
        "stream": stream,
    }
    if temperature is not None:
        request_kwargs["temperature"] = temperature
    text_format = _build_text_format(
        response_mime_type=response_mime_type,
        response_schema=response_schema,
        structured_output_name=structured_output_name,
    )
    if text_format:
        request_kwargs["text"] = text_format
    if search_enabled:
        request_kwargs["tools"] = [{"type": "web_search_preview"}]
        request_kwargs["tool_choice"] = "auto"
        request_kwargs["include"] = ["web_search_call.action.sources"]
    return request_kwargs


def _build_client(runtime: AzureRuntime):
    from openai import OpenAI

    return OpenAI(api_key=runtime.api_key, base_url=runtime.base_url)


def generate_response(
    *,
    runtime: AzureRuntime,
    input_messages: list[dict[str, object]],
    instructions: str,
    max_output_tokens: int,
    temperature: float | None = None,
    search_enabled: bool = False,
    response_mime_type: str | None = None,
    response_schema: dict[str, Any] | None = None,
    structured_output_name: str | None = None,
) -> AzureRouterResult:
    client = _build_client(runtime)
    request_kwargs = _build_request_kwargs(
        runtime=runtime,
        input_messages=input_messages,
        instructions=instructions,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        search_enabled=search_enabled,
        response_mime_type=response_mime_type,
        response_schema=response_schema,
        structured_output_name=structured_output_name,
        stream=False,
    )
    response = client.responses.create(**request_kwargs)
    return AzureRouterResult(
        text=_extract_response_text(response),
        usage_metadata=_coerce_usage(_get_attr(response, "usage")),
        grounding_metadata=normalize_grounding(response),
        response=response,
    )


def stream_response(
    *,
    runtime: AzureRuntime,
    input_messages: list[dict[str, object]],
    instructions: str,
    max_output_tokens: int,
    temperature: float | None = None,
    search_enabled: bool = False,
    response_mime_type: str | None = None,
    response_schema: dict[str, Any] | None = None,
    structured_output_name: str | None = None,
) -> Iterator[AzureStreamChunk]:
    client = _build_client(runtime)
    request_kwargs = _build_request_kwargs(
        runtime=runtime,
        input_messages=input_messages,
        instructions=instructions,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        search_enabled=search_enabled,
        response_mime_type=response_mime_type,
        response_schema=response_schema,
        structured_output_name=structured_output_name,
        stream=True,
    )
    stream = client.responses.create(**request_kwargs)
    for event in stream:
        event_type = _get_attr(event, "type", "")
        if event_type == "response.output_text.delta":
            delta = _get_attr(event, "delta", "") or ""
            if delta:
                yield AzureStreamChunk(text_delta=delta)
            continue
        if event_type == "response.reasoning_summary_text.delta":
            delta = _get_attr(event, "delta", "") or ""
            if delta:
                yield AzureStreamChunk(thought_delta=delta)
            continue
        if event_type == "response.completed":
            response = _get_attr(event, "response")
            usage_metadata = _coerce_usage(_get_attr(response, "usage"))
            grounding_metadata = normalize_grounding(response)
            if usage_metadata or grounding_metadata:
                yield AzureStreamChunk(
                    usage_metadata=usage_metadata,
                    grounding_metadata=grounding_metadata,
                )
            continue
        if event_type == "error":
            error = _get_attr(event, "error")
            raise RuntimeError(
                _get_attr(error, "message")
                or str(error)
                or "Azure OpenAI stream error."
            )