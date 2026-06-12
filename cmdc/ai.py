"""Provider-agnostic AI call driven by the templates in config."""

import requests

from . import config


class AIError(Exception):
    pass


def _fill(obj, vars: dict):
    if isinstance(obj, str):
        for k, v in vars.items():
            obj = obj.replace("{" + k + "}", v)
        return obj
    if isinstance(obj, dict):
        return {k: _fill(v, vars) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill(v, vars) for v in obj]
    return obj


def _dig(data, path: str):
    cur = data
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def correct(text: str, cfg: dict) -> str:
    provider = cfg["provider"]
    tpl = cfg["providers"].get(provider)
    if not tpl:
        raise AIError(f"Unknown provider: {provider}")

    api_key = config.api_key_for(cfg)
    if not api_key:
        env = tpl.get("api_key_env", "")
        raise AIError(f"No API key for {provider}. Set it in the menu or export {env}.")

    vars = {
        "api_key": api_key,
        "model": config.model_for(cfg),
        "system_prompt": cfg["system_prompt"],
        "text": text,
    }
    url = _fill(tpl["url"], vars)
    headers = _fill(tpl.get("headers", {}), vars)
    body = _fill(tpl["body"], vars)

    try:
        resp = requests.post(url, headers=headers, json=body,
                             timeout=cfg.get("timeout_sec", 30))
    except requests.RequestException as e:
        raise AIError(f"Request failed: {e}") from e

    if resp.status_code != 200:
        raise AIError(f"{provider} HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        result = _dig(resp.json(), tpl["response_path"])
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise AIError(f"Bad response shape ({e}): {resp.text[:200]}") from e

    if not isinstance(result, str) or not result.strip():
        raise AIError("Empty result from API")
    return result.strip()


def apply_substitutions(text: str, cfg: dict) -> str:
    if not cfg.get("substitutions_enabled"):
        return text
    for src, dst in cfg.get("substitutions", {}).items():
        text = text.replace(src, dst)
    return text
