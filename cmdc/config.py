"""Config: ~/.config/cmdc/config.json — merged over defaults on load."""

import copy
import json
import os
import tempfile
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "cmdc"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_PROMPT = (
    "You are a grammar and style corrector. Fix grammar, spelling, punctuation "
    "and awkward phrasing in the user's text. Preserve the original meaning, "
    "language, tone and formatting (line breaks, lists, markdown). "
    "Output ONLY the corrected text — no explanations, no quotes around it."
)

DEFAULT_GEMINI_MODEL = "gemini-3.7-flash"
DEFAULT_GEMINI_THINKING_CONFIG = {"thinkingBudget": 0}
LEGACY_GEMINI_DEFAULT_MODELS = {"gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.6-flash"}

# Provider templates. Placeholders {api_key} {model} {system_prompt} {text} {endpoint}
# are substituted into url/headers/body strings. response_path is a
# dot-separated path into the response JSON (ints = list indices).
DEFAULTS = {
    "enabled": True,
    "provider": "openai",
    "model": "",  # empty -> provider's default_model
    "api_keys": {},  # {"openai": "sk-..."}; falls back to api_key_env
    "endpoints": {},  # {"gemini": "https://..."}; falls back to endpoint_env / default_endpoint
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
            "url": "{endpoint}/v1/chat/completions",
            "default_endpoint": "https://api.openai.com",
            "endpoint_env": "OPENAI_BASE_URL",
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
            "url": "{endpoint}/v1beta/models/{model}:generateContent",
            "default_endpoint": "https://generativelanguage.googleapis.com",
            "endpoint_env": "GEMINI_BASE_URL",
            "headers": {
                "x-goog-api-key": "{api_key}",
                "Content-Type": "application/json",
            },
            "body": {
                "system_instruction": {"parts": [{"text": "{system_prompt}"}]},
                "contents": [{"role": "user", "parts": [{"text": "{text}"}]}],
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
            "url": "{endpoint}/v1/messages",
            "default_endpoint": "https://api.anthropic.com",
            "endpoint_env": "ANTHROPIC_BASE_URL",
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
    if "endpoints" not in cfg or not isinstance(cfg.get("endpoints"), dict):
        cfg["endpoints"] = {}
        changed = True

    gemini = cfg.get("providers", {}).get("gemini")
    if isinstance(gemini, dict):
        if gemini.get("default_model") in LEGACY_GEMINI_DEFAULT_MODELS:
            gemini["default_model"] = DEFAULT_GEMINI_MODEL
            changed = True

        if not gemini.get("default_endpoint"):
            gemini["default_endpoint"] = "https://generativelanguage.googleapis.com"
            changed = True

        if not gemini.get("endpoint_env"):
            gemini["endpoint_env"] = "GEMINI_BASE_URL"
            changed = True

        if gemini.get("url") == "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent":
            gemini["url"] = "{endpoint}/v1beta/models/{model}:generateContent"
            changed = True

        body = gemini.get("body")
        if isinstance(body, dict):
            contents = body.get("contents")
            if isinstance(contents, list) and contents and isinstance(contents[0], dict):
                if "role" not in contents[0]:
                    contents[0]["role"] = "user"
                    changed = True

            generation_config = body.get("generationConfig")
            if isinstance(generation_config, dict):
                thinking_config = generation_config.get("thinkingConfig")
                if thinking_config != DEFAULT_GEMINI_THINKING_CONFIG:
                    generation_config["thinkingConfig"] = copy.deepcopy(
                        DEFAULT_GEMINI_THINKING_CONFIG
                    )
                    changed = True

    for name, default_tpl in DEFAULTS["providers"].items():
        prov = cfg.get("providers", {}).get(name)
        if isinstance(prov, dict):
            if "default_endpoint" not in prov and "default_endpoint" in default_tpl:
                prov["default_endpoint"] = default_tpl["default_endpoint"]
                changed = True
            if "endpoint_env" not in prov and "endpoint_env" in default_tpl:
                prov["endpoint_env"] = default_tpl["endpoint_env"]
                changed = True
            if name == "openai" and prov.get("url") == "https://api.openai.com/v1/chat/completions":
                prov["url"] = "{endpoint}/v1/chat/completions"
                changed = True
            elif name == "anthropic" and prov.get("url") == "https://api.anthropic.com/v1/messages":
                prov["url"] = "{endpoint}/v1/messages"
                changed = True

    return changed


def load() -> dict:
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
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
    fd, temporary_name = tempfile.mkstemp(prefix=".config-", dir=CONFIG_DIR)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
            json.dump(cfg, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, CONFIG_PATH)
        os.chmod(CONFIG_PATH, 0o600)  # may hold API keys
    finally:
        temporary_path.unlink(missing_ok=True)


def model_for(cfg: dict) -> str:
    return cfg["model"] or cfg["providers"][cfg["provider"]]["default_model"]


def endpoint_for(cfg: dict, provider: str | None = None) -> str:
    prov = provider or cfg["provider"]
    # 1. Configured endpoint
    ep = cfg.get("endpoints", {}).get(prov, "")
    if isinstance(ep, str):
        ep = ep.strip()
        if ep.lower() in ("null", "none", "default"):
            ep = ""
    else:
        ep = ""
    if ep:
        return ep.rstrip("/")
    # 2. Provider's endpoint env var
    tpl = cfg.get("providers", {}).get(prov, {})
    env_var = tpl.get("endpoint_env", "")
    if env_var:
        val = os.environ.get(env_var, "").strip()
        if val and val.lower() not in ("null", "none", "default"):
            return val.rstrip("/")
    # 3. Extra standard fallback env vars
    if prov == "gemini":
        for extra in ("GEMINI_ENDPOINT", "VERTEX_PROXY_URL"):
            val = os.environ.get(extra, "").strip()
            if val and val.lower() not in ("null", "none", "default"):
                return val.rstrip("/")
    elif prov == "openai":
        val = os.environ.get("OPENAI_ENDPOINT", "").strip()
        if val and val.lower() not in ("null", "none", "default"):
            return val.rstrip("/")
    # 4. Default endpoint in provider template
    default_ep = tpl.get("default_endpoint", "").strip()
    if default_ep:
        return default_ep.rstrip("/")
    return ""


def api_key_for(cfg: dict, provider: str | None = None) -> str:
    prov = provider or cfg["provider"]
    key = cfg.get("api_keys", {}).get(prov, "").strip()

    endpoint = endpoint_for(cfg, prov)
    is_custom_gemini = (
        prov == "gemini"
        and bool(endpoint)
        and "generativelanguage.googleapis.com" not in endpoint
    )

    if is_custom_gemini:
        if key and not key.startswith("AIzaSy"):
            return key
        for env_var in ("VERTEX_PROXY_API_KEY", "LLM_PROXY_TOKEN"):
            val = os.environ.get(env_var, "").strip()
            if val:
                return val
        opencode_key_path = Path.home() / ".config" / "opencode" / "vertex-proxy-api-key"
        if opencode_key_path.is_file():
            try:
                val = opencode_key_path.read_text().strip()
                if val:
                    return val
            except OSError:
                pass
        if key:
            return key

    if key:
        return key

    env = cfg.get("providers", {}).get(prov, {}).get("api_key_env", "")
    key = os.environ.get(env, "").strip() if env else ""
    if key:
        return key

    if prov == "gemini":
        for env_var in ("VERTEX_PROXY_API_KEY", "LLM_PROXY_TOKEN"):
            val = os.environ.get(env_var, "").strip()
            if val:
                return val
        opencode_key_path = Path.home() / ".config" / "opencode" / "vertex-proxy-api-key"
        if opencode_key_path.is_file():
            try:
                val = opencode_key_path.read_text().strip()
                if val:
                    return val
            except OSError:
                pass

    return ""
