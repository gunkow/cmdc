"""Config: ~/.config/cmdc/config.json — merged over defaults on load."""

import copy
import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "cmdc"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_PROMPT = (
    "You are a grammar and style corrector. Fix grammar, spelling, punctuation "
    "and awkward phrasing in the user's text. Preserve the original meaning, "
    "language, tone and formatting (line breaks, lists, markdown). "
    "Output ONLY the corrected text — no explanations, no quotes around it."
)

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_THINKING_CONFIG = {"thinkingLevel": "minimal"}
LEGACY_GEMINI_DEFAULT_MODELS = {"gemini-2.5-flash"}

# Provider templates. Placeholders {api_key} {model} {system_prompt} {text}
# are substituted into url/headers/body strings. response_path is a
# dot-separated path into the response JSON (ints = list indices).
DEFAULTS = {
    "enabled": True,
    "provider": "openai",
    "model": "",  # empty -> provider's default_model
    "api_keys": {},  # {"openai": "sk-..."}; falls back to api_key_env
    "system_prompt": DEFAULT_PROMPT,
    "substitutions_enabled": True,
    "substitutions": {
        "—": "-",   # em dash
        "–": "-",   # en dash
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
    },
    "trigger_count": 3,
    "trigger_window_sec": 1.0,
    "max_chars": 12000,
    "timeout_sec": 30,
    "providers": {
        "openai": {
            "url": "https://api.openai.com/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer {api_key}",
                "Content-Type": "application/json",
            },
            "body": {
                "model": "{model}",
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": "{system_prompt}"},
                    {"role": "user", "content": "{text}"},
                ],
            },
            "response_path": "choices.0.message.content",
            "default_model": "gpt-5.4-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "gemini": {
            "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            "headers": {
                "x-goog-api-key": "{api_key}",
                "Content-Type": "application/json",
            },
            "body": {
                "system_instruction": {"parts": [{"text": "{system_prompt}"}]},
                "contents": [{"parts": [{"text": "{text}"}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "thinkingConfig": DEFAULT_GEMINI_THINKING_CONFIG,
                },
            },
            "response_path": "candidates.0.content.parts.0.text",
            "default_model": DEFAULT_GEMINI_MODEL,
            "api_key_env": "GEMINI_API_KEY",
        },
        "anthropic": {
            "url": "https://api.anthropic.com/v1/messages",
            "headers": {
                "x-api-key": "{api_key}",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            "body": {
                "model": "{model}",
                "max_tokens": 4096,
                "system": "{system_prompt}",
                "messages": [{"role": "user", "content": "{text}"}],
            },
            "response_path": "content.0.text",
            "default_model": "claude-haiku-4-5-20251001",
            "api_key_env": "ANTHROPIC_API_KEY",
        },
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _migrate(cfg: dict) -> bool:
    changed = False
    gemini = cfg.get("providers", {}).get("gemini")
    if isinstance(gemini, dict):
        if gemini.get("default_model") in LEGACY_GEMINI_DEFAULT_MODELS:
            gemini["default_model"] = DEFAULT_GEMINI_MODEL
            changed = True

        body = gemini.get("body")
        generation_config = body.get("generationConfig") if isinstance(body, dict) else None
        if isinstance(generation_config, dict):
            thinking_config = generation_config.get("thinkingConfig")
            if thinking_config != DEFAULT_GEMINI_THINKING_CONFIG:
                generation_config["thinkingConfig"] = copy.deepcopy(
                    DEFAULT_GEMINI_THINKING_CONFIG
                )
                changed = True

    return changed


def load() -> dict:
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            user = {}
        cfg = _merge(DEFAULTS, user)
        if _migrate(cfg):
            save(cfg)
        return cfg
    cfg = copy.deepcopy(DEFAULTS)
    save(cfg)
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    os.chmod(CONFIG_PATH, 0o600)  # may hold API keys


def model_for(cfg: dict) -> str:
    return cfg["model"] or cfg["providers"][cfg["provider"]]["default_model"]


def api_key_for(cfg: dict) -> str:
    provider = cfg["provider"]
    key = cfg["api_keys"].get(provider, "")
    if not key:
        env = cfg["providers"][provider].get("api_key_env", "")
        key = os.environ.get(env, "") if env else ""
    return key
