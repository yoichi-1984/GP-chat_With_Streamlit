from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AzureUsageMetadata:
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    total_token_count: int = 0
    thoughts_token_count: int = 0
    cached_content_token_count: int = 0
    traffic_type: str | None = None


@dataclass
class AzureStreamChunk:
    text_delta: str = ""
    thought_delta: str = ""
    usage_metadata: AzureUsageMetadata | None = None
    grounding_metadata: dict[str, object] | None = None
    route: str = "azure_fallback"
    app_retry_count: int = 0
    sdk_http_headers: dict[str, str] | None = None
    provider: str = "azure"


@dataclass
class AzureRouterResult:
    text: str = ""
    usage_metadata: AzureUsageMetadata | None = None
    grounding_metadata: dict[str, object] | None = None
    route: str = "azure_fallback"
    app_retry_count: int = 0
    sdk_http_headers: dict[str, str] | None = None
    provider: str = "azure"
    response: Any = None


@dataclass
class AzureMaterializedContext:
    messages: list[dict[str, object]]
    system_instruction: str
    available_files_map: dict[str, str] = field(default_factory=dict)
    file_attachments_meta: list[dict[str, object]] = field(default_factory=list)
    retry_context_snapshot: list[dict[str, object]] = field(default_factory=list)

    def clone_retry_context(self) -> list[dict[str, object]]:
        return copy.deepcopy(self.retry_context_snapshot)


@dataclass
class AzureModeResult:
    full_response: str = ""
    thought_log: str = ""
    system_instruction: str = ""
    usage_metadata: AzureUsageMetadata | None = None
    grounding_metadata: dict[str, object] | None = None
    mode_meta: dict[str, object] = field(default_factory=dict)
    available_files_map: dict[str, str] = field(default_factory=dict)
    file_attachments_meta: list[dict[str, object]] = field(default_factory=list)
    retry_context_snapshot: list[dict[str, object]] = field(default_factory=list)
    images: list[str] = field(default_factory=list)