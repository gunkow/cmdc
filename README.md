# cmdc

Instant AI text correction anywhere on macOS with a triple press of **Cmd+C**.

Select text in any app, press **Cmd+C** 3 times within 1 second, and cmdc sends
the copied text to your chosen AI provider. The corrected result is placed on
the clipboard and pasted over the original selection.

## Features

- Works in any macOS app that supports copy and paste.
- Supports OpenAI, Gemini, Anthropic, and custom JSON APIs.
- Provides an editable system prompt and per-provider model selection.
- Stores API keys locally or reads them from environment variables.
- Optionally normalizes dashes, quotation marks, and ellipses.
- Shows trigger and processing status in the menu bar.
- Includes a CLI for testing the correction pipeline without global hotkeys.

## Requirements

- macOS
- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/)
- An API key for at least one supported provider

cmdc also needs 2 macOS permissions:

- **Input Monitoring** to detect the global Cmd+C sequence.
- **Accessibility** to paste the corrected text into the active app.

## Quick start

```bash
git clone https://github.com/gunkow/cmdc.git
cd cmdc
uv sync
uv run cmdc
```

On first launch, grant the required permissions under **System Settings →
Privacy & Security**, then restart cmdc.

Choose a provider from the menu bar and set its API key with **Set API Key…**.
Alternatively, export one of the supported environment variables before
launching cmdc:

| Provider | Environment variable | Endpoint env | Default model |
|---|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `OPENAI_BASE_URL` | `gpt-5.4-mini` |
| Gemini | `GEMINI_API_KEY` | `GEMINI_BASE_URL` | `gemini-3.7-flash` |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_BASE_URL` | `claude-haiku-4-5-20251001` |

When cmdc is launched from Finder or Login Items, shell environment variables
may not be available. In that case, save the key through the menu bar.

## Build the macOS application

The checked-in py2app recipe creates a native menu-bar application that can be
opened from Finder, Launchpad, or Login Items:

```bash
cd macos
BUILD_DIR="$(mktemp -d /tmp/cmdc-app.XXXXXX)"
PYTHON_BIN="${PYTHON_BIN:-$(brew --prefix python)/bin/python3}"
uv run --python "$PYTHON_BIN" --no-cache \
  --with py2app --with-editable .. \
  python setup.py py2app \
  --dist-dir "$BUILD_DIR/dist" \
  --bdist-base "$BUILD_DIR/build"
codesign --force --deep --sign - "$BUILD_DIR/dist/cmdc.app"
open "$BUILD_DIR/dist"
```

The default uses Homebrew's Python on both Apple Silicon and Intel Macs.
`PYTHON_BIN` must point to a Python 3.11+ framework build that py2app can bundle;
override it when Homebrew Python is not the intended packaging interpreter.

Drag `cmdc.app` from the opened build directory into **Applications**. Quit any
existing copy before replacing it. The ad-hoc signature is suitable for a local
build; distributing the app to other Macs requires a Developer ID signature and
notarization. Replacing an ad-hoc-signed local build can also change its macOS
privacy identity; if the trigger stops working, remove and re-enable cmdc under
Input Monitoring and Accessibility.

The recipe deliberately includes a few details that prevent subtle Finder and
Launchpad failures:

- `LSUIElement` makes cmdc a menu-bar app while still allowing API-key and prompt
  dialogs to become active and accept keyboard input. `LSBackgroundOnly` must not
  be used for an interactive menu-bar app.
- Permission checks only preflight Input Monitoring and Accessibility at startup.
  Requesting permissions or showing a modal alert before the event loop starts can
  leave the app running with no visible menu.
- `pynput` and `charset_normalizer` are collected explicitly because their dynamic
  or compiled helper modules are not always discovered by py2app automatically.
- The launcher is named `launcher.py` and its bundle entry point is named `cmdc`;
  naming the source file `cmdc.py` would shadow the real `cmdc` package.
- `--no-cache --with-editable ..` prevents uv from reusing a stale local wheel while
  iterating on the application source.
- Configuration files are always read and written as UTF-8 because apps launched
  by Finder can start with a different locale from an interactive shell.

After the first launch, open cmdc's **Permissions required** menu and enable cmdc
in both macOS privacy panes. Restart the app after changing either permission.

## Usage

1. Select text in any application.
2. Press **Cmd+C** 3 times within 1 second.
3. Wait for the menu-bar icon to change from `⌘…` to `⌘✓`.
4. The corrected text replaces the selection automatically.

### Menu bar

| Item | Description |
|---|---|
| **Enabled** | Enables or disables the global trigger. |
| **Permissions required** | Opens the Input Monitoring and Accessibility privacy panes when either permission is missing. |
| **Provider** | Selects OpenAI, Gemini, Anthropic, or a configured custom provider. |
| **Model: …** | Overrides the provider's default model. Leave it empty to use the default. |
| **Endpoint: …** | Overrides the provider's base endpoint URL (e.g. for private Vertex native proxies or local servers). |
| **Set API Key…** | Saves an API key for the selected provider. |
| **Edit Prompt…** | Opens the system-prompt editor. Enter inserts a line break; **Save** applies it. |
| **Replace symbols** | Converts typographic dashes, quotes, and ellipses to configured replacements. |
| **Open Config File** | Opens the complete JSON configuration. |
| **Open Log File** | Opens the current log at `/tmp/cmdc.log`. |

## Configuration

Configuration is stored in `~/.config/cmdc/config.json` with file mode `0600`.
The app creates this file from its defaults on first launch and updates it when
settings are changed through the menu bar.

Common settings include:

| Setting | Default | Description |
|---|---:|---|
| `trigger_count` | `3` | Number of rapid Cmd+C presses required. |
| `trigger_window_sec` | `1.0` | Time window for the trigger sequence. |
| `max_chars` | `12000` | Maximum clipboard-text length sent to the provider. |
| `timeout_sec` | `30` | HTTP request timeout in seconds. |
| `endpoints` | `{}` | Per-provider custom base URLs or endpoints. |
| `substitutions_enabled` | `true` | Enables response post-processing. |
| `substitutions` | built-in map | Character replacements applied before pasting. |

Gemini uses `gemini-3.7-flash` with `thinkingBudget: 0` by default to keep short correction calls
instant.

### Custom endpoints and proxies

To route Gemini requests through a private Vertex AI Native proxy:
1. In the menu bar, click **Endpoint: …** and enter:
   `https://omi-gemini-native-proxy-775418318631.europe-west2.run.app`
   (or export `GEMINI_BASE_URL` in your shell environment).
2. Set the bearer token under **Set API Key…** or export `VERTEX_PROXY_API_KEY`. (If `~/.config/opencode/vertex-proxy-api-key` is present, it is picked up automatically).

Existing configurations that still use legacy default models are migrated automatically.

### Custom providers

Provider integrations are JSON request templates. Any API that accepts JSON and
returns JSON can be added under `providers` in the config file:

```jsonc
{
  "providers": {
    "myprovider": {
      "url": "https://api.example.com/v1/chat/completions",
      "headers": {
        "Authorization": "Bearer {api_key}",
        "Content-Type": "application/json"
      },
      "body": {
        "model": "{model}",
        "messages": [
          { "role": "system", "content": "{system_prompt}" },
          { "role": "user", "content": "{text}" }
        ]
      },
      "response_path": "choices.0.message.content",
      "default_model": "my-model",
      "api_key_env": "MYPROVIDER_API_KEY"
    }
  }
}
```

Available placeholders are `{api_key}`, `{model}`, `{system_prompt}`, and
`{text}`. `response_path` is a dot-separated path into the response JSON; list
indexes are written as numbers, for example `choices.0.message.content`.

## Command-line usage

Use `cmdc-fix` to test the active provider, prompt, and substitutions without
the menu-bar app:

```bash
uv run cmdc-fix "this are a example with mistakes"
echo "some text" | uv run cmdc-fix
```

## How it works

```mermaid
sequenceDiagram
    actor User
    participant App as "Active macOS app"
    participant cmdc as "cmdc menu-bar app"
    participant API as "AI provider"

    User->>App: Select text
    User->>App: Press Cmd+C 3 times
    App-->>cmdc: Copy selection to clipboard
    cmdc->>cmdc: Detect rapid key sequence
    cmdc->>API: Send system prompt and clipboard text
    API-->>cmdc: Return corrected text
    cmdc->>cmdc: Apply configured substitutions
    cmdc->>App: Update clipboard and send Cmd+V
    App-->>User: Replace the selected text
```

The system prompt and clipboard text are sent as separate request fields. The
exact provider request and response shapes are defined in `cmdc/config.py`.

## Troubleshooting

### The trigger is not detected

Grant Input Monitoring permission to the process that launches cmdc. If you
switch between a terminal launch and an application bundle, macOS may treat
them as different permission identities.

### The result is generated but not pasted

Grant Accessibility permission to cmdc, then restart it.

### The API key is not found

Set the key through **Set API Key…**. Apps launched from Finder or Login Items
do not necessarily inherit variables from your interactive shell.

### A correction fails

Open **Open Log File** from the menu bar or inspect `/tmp/cmdc.log`:

```bash
tail -f /tmp/cmdc.log
```

## Development

The project is intentionally small:

| Module | Responsibility |
|---|---|
| `cmdc/app.py` | Menu-bar UI and correction workflow. |
| `cmdc/hotkey.py` | Global multi-press detection. |
| `cmdc/clipboard.py` | Clipboard access and synthetic Cmd+V. |
| `cmdc/ai.py` | Provider-independent HTTP request handling. |
| `cmdc/config.py` | Defaults, persistence, migrations, and provider templates. |
| `cmdc/cli.py` | Command-line entry point. |

Run the regression tests and basic source checks with:

```bash
uv run python -m unittest discover -s tests -v
uv run python -m compileall cmdc
git diff --check
```

Restart the menu-bar app after changing the source.

## Roadmap

- Add a separate global shortcut for one-off custom instructions.

## Acknowledgements

Inspired by [cmd-c.app](https://cmd-c.app/).
