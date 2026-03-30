from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


FAULT_INJECTION_PATH = Path.cwd() / "dev" / "fault_injection.local.toml"
SUPPORTED_MODES = (
    "normal",
    "special",
    "research",
    "reasoning",
    "report",
    "auto_plot_fix",
)


@dataclass(frozen=True)
class ModeFaultRule:
    inject_terminal_429: bool = False
    force_azure_branch: bool = False


@dataclass(frozen=True)
class FaultInjectionConfig:
    enabled: bool = False
    modes: dict[str, ModeFaultRule] = field(default_factory=dict)

    def get_mode_rule(self, mode: str) -> ModeFaultRule:
        return self.modes.get(mode, ModeFaultRule())


class SyntheticTerminal429Error(RuntimeError):
    def __init__(self, mode: str):
        payload = {
            "error": {
                "code": 429,
                "message": (
                    f"Synthetic terminal 429 injected for mode '{mode}'. "
                    "This simulates a generic upstream rate-limit failure."
                ),
                "status": "RESOURCE_EXHAUSTED",
            }
        }
        self.code = 429
        self.status_code = 429
        self.status = "RESOURCE_EXHAUSTED"
        self.payload = payload
        super().__init__(f"429 {self.status}. {payload}")


def load_fault_injection_config() -> FaultInjectionConfig:
    if not FAULT_INJECTION_PATH.exists():
        return FaultInjectionConfig()

    with FAULT_INJECTION_PATH.open("rb") as f:
        raw = tomllib.load(f)

    global_enabled = bool(raw.get("global", {}).get("enabled", False))
    modes: dict[str, ModeFaultRule] = {}
    raw_modes = raw.get("modes", {})
    for mode in SUPPORTED_MODES:
        raw_rule = raw_modes.get(mode, {})
        modes[mode] = ModeFaultRule(
            inject_terminal_429=bool(raw_rule.get("inject_terminal_429", False)),
            force_azure_branch=bool(raw_rule.get("force_azure_branch", False)),
        )
    return FaultInjectionConfig(enabled=global_enabled, modes=modes)


def should_force_azure_branch(mode: str, cfg: FaultInjectionConfig) -> bool:
    if not cfg.enabled:
        return False
    return bool(cfg.get_mode_rule(mode).force_azure_branch)


def should_inject_terminal_429(mode: str, cfg: FaultInjectionConfig) -> bool:
    if not cfg.enabled:
        return False
    rule = cfg.get_mode_rule(mode)
    if rule.force_azure_branch:
        return False
    return bool(rule.inject_terminal_429)


def build_synthetic_terminal_429(mode: str) -> Exception:
    return SyntheticTerminal429Error(mode)