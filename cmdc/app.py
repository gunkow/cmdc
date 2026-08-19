"""Menu bar app: triple Cmd+C -> AI-correct the copied text -> paste in place."""

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import rumps
from Foundation import NSObject

log = logging.getLogger("cmdc")

from . import ai, clipboard, config
from .hotkey import MultiPressListener

ICON_IDLE = "⌘C"
ICON_BUSY = "⌘…"
ICON_OK = "⌘✓"
ICON_ERR = "⌘✗"
ICON_OFF = "⌘×"
LOG_PATH = Path(os.environ.get("CMDC_LOG_PATH", "/tmp/cmdc.log"))


class _PromptTextDelegate(NSObject):
    def control_textView_doCommandBySelector_(self, _control, text_view, command):
        if command == "insertNewline:":
            text_view.insertNewlineIgnoringFieldEditor_(None)
            return True
        return False


class CmdCApp(rumps.App):
    def __init__(self, permissions_ok: bool = True):
        super().__init__("cmdc", title=ICON_IDLE, quit_button="Quit")
        self.permissions_ok = permissions_ok
        self.cfg = config.load()
        self._busy = threading.Lock()
        self._build_menu()
        self._sync_idle_icon()
        self.listener = MultiPressListener(
            actions={"c": self._on_triple_copy},
            count=self.cfg["trigger_count"],
            window=self.cfg["trigger_window_sec"],
            on_progress=self._on_hotkey_progress,
        )
        self.listener.start()
        log.info("ready: provider=%s model=%s enabled=%s",
                 self.cfg["provider"], config.model_for(self.cfg),
                 self.cfg["enabled"])

    # ---------- menu ----------

    def _build_menu(self):
        self.item_enabled = rumps.MenuItem("Enabled", callback=self._toggle_enabled)
        self.item_enabled.state = self.cfg["enabled"]

        self.permissions_menu = rumps.MenuItem("Permissions required")
        self.permissions_menu.add(
            rumps.MenuItem(
                "Open Input Monitoring…", callback=self._open_input_monitoring
            )
        )
        self.permissions_menu.add(
            rumps.MenuItem("Open Accessibility…", callback=self._open_accessibility)
        )

        self.provider_menu = rumps.MenuItem("Provider")
        for name in self.cfg["providers"]:
            item = rumps.MenuItem(name, callback=self._pick_provider)
            item.state = name == self.cfg["provider"]
            self.provider_menu.add(item)

        self.item_model = rumps.MenuItem("", callback=self._edit_model)
        self._refresh_model_title()
        self.item_endpoint = rumps.MenuItem("", callback=self._edit_endpoint)
        self._refresh_endpoint_title()
        self.item_key = rumps.MenuItem("Set API Key…", callback=self._edit_key)
        self.item_prompt = rumps.MenuItem("Edit Prompt…", callback=self._edit_prompt)

        self.item_subs = rumps.MenuItem(
            "Replace symbols (— “” …)", callback=self._toggle_subs
        )
        self.item_subs.state = self.cfg["substitutions_enabled"]
        self.item_perm = rumps.MenuItem("Check Permissions…", callback=self._menu_check_permissions)
        self.item_cfg = rumps.MenuItem("Open Config File", callback=self._open_config)
        self.item_log = rumps.MenuItem("Open Log File", callback=self._open_log)

        menu = [self.item_enabled]
        if not self.permissions_ok:
            menu.append(self.permissions_menu)
        menu.extend([
            None,
            self.provider_menu,
            self.item_model,
            self.item_endpoint,
            self.item_key,
            self.item_prompt,
            None,
            self.item_subs,
            self.item_perm,
            self.item_cfg,
            self.item_log,
            None,
        ])
        self.menu = menu

    def _refresh_model_title(self):
        self.item_model.title = f"Model: {config.model_for(self.cfg)} …"

    def _refresh_endpoint_title(self):
        provider = self.cfg["provider"]
        custom = self.cfg.get("endpoints", {}).get(provider, "").strip()
        if custom:
            display = custom.replace("https://", "").replace("http://", "").rstrip("/")
            if len(display) > 28:
                display = display[:25] + "…"
            self.item_endpoint.title = f"Endpoint: {display} …"
        else:
            self.item_endpoint.title = "Endpoint: (default) …"

    def _sync_idle_icon(self):
        if not self.permissions_ok:
            self.title = ICON_ERR
        else:
            self.title = ICON_IDLE if self.cfg["enabled"] else ICON_OFF

    def _sync_idle_icon_if_ready(self):
        if not self._busy.locked():
            self._sync_idle_icon()

    def _toggle_enabled(self, item):
        self.cfg["enabled"] = not self.cfg["enabled"]
        item.state = self.cfg["enabled"]
        self._sync_idle_icon()
        config.save(self.cfg)

    def _pick_provider(self, item):
        self.cfg["provider"] = item.title
        for it in self.provider_menu.values():
            it.state = it.title == item.title
        self._refresh_model_title()
        self._refresh_endpoint_title()
        config.save(self.cfg)

    def _edit_model(self, _):
        provider = self.cfg["provider"]
        default = self.cfg["providers"][provider]["default_model"]
        win = rumps.Window(
            message=f"Model for {provider} (empty = default: {default})",
            title="cmdc — Model",
            default_text=self.cfg["model"],
            ok="Save",
            cancel="Cancel",
            dimensions=(320, 24),
        )
        resp = win.run()
        if resp.clicked:
            val = resp.text.strip()
            if val.lower() in ("null", "none", "default"):
                val = ""
            self.cfg["model"] = val
            self._refresh_model_title()
            config.save(self.cfg)

    def _edit_endpoint(self, _):
        provider = self.cfg["provider"]
        default_ep = self.cfg["providers"][provider].get("default_endpoint", "")
        env = self.cfg["providers"][provider].get("endpoint_env", "")
        current = self.cfg.get("endpoints", {}).get(provider, "")
        msg = (
            f"Endpoint / Base URL for {provider} (stored in ~/.config/cmdc/config.json).\n"
            f"Leave empty to use default: {default_ep}"
        )
        if env:
            msg += f"\nOr export {env}."
        win = rumps.Window(
            message=msg,
            title="cmdc — Custom Endpoint",
            default_text=current,
            ok="Save",
            cancel="Cancel",
            dimensions=(360, 24),
        )
        resp = win.run()
        if resp.clicked:
            val = resp.text.strip()
            if val.lower() in ("null", "none", "default"):
                val = ""
            self.cfg.setdefault("endpoints", {})[provider] = val
            self._refresh_endpoint_title()
            config.save(self.cfg)

    def _edit_key(self, _):
        provider = self.cfg["provider"]
        env = self.cfg["providers"][provider].get("api_key_env", "")
        win = rumps.Window(
            message=(
                f"API key for {provider} (stored in ~/.config/cmdc/config.json).\n"
                f"Leave empty to use the {env} env var."
            ),
            title="cmdc — API Key",
            default_text=self.cfg["api_keys"].get(provider, ""),
            ok="Save",
            cancel="Cancel",
            dimensions=(320, 24),
        )
        resp = win.run()
        if resp.clicked:
            self.cfg["api_keys"][provider] = resp.text.strip()
            config.save(self.cfg)

    def _edit_prompt(self, _):
        win = rumps.Window(
            message="System prompt sent with your text:",
            title="cmdc — Prompt",
            default_text=self.cfg["system_prompt"],
            ok="Save",
            cancel="Cancel",
            dimensions=(680, 360),
        )
        prompt_delegate = _PromptTextDelegate.alloc().init()
        win._textfield.setDelegate_(prompt_delegate)
        win._prompt_text_delegate = prompt_delegate
        resp = win.run()
        if resp.clicked and resp.text.strip():
            self.cfg["system_prompt"] = resp.text.strip()
            config.save(self.cfg)

    def _toggle_subs(self, item):
        self.cfg["substitutions_enabled"] = not self.cfg["substitutions_enabled"]
        item.state = self.cfg["substitutions_enabled"]
        config.save(self.cfg)

    def _menu_check_permissions(self, _):
        listen, post = True, True
        try:
            from Quartz import CGPreflightListenEventAccess, CGPreflightPostEventAccess
            listen = bool(CGPreflightListenEventAccess())
            post = bool(CGPreflightPostEventAccess())
        except ImportError:
            pass
        if listen and post:
            rumps.alert(
                title="Permissions OK",
                message="cmdc has both Input Monitoring and Accessibility permissions.",
            )
        else:
            missing = []
            if not listen:
                missing.append("Input Monitoring")
            if not post:
                missing.append("Accessibility")
            rumps.alert(
                title="cmdc needs permissions",
                message=(
                    f"Missing: {', '.join(missing)}\n\n"
                    "System Settings → Privacy & Security:\n"
                    "  • Input Monitoring → enable cmdc (or Terminal)\n"
                    "  • Accessibility → enable cmdc (or Terminal)\n\n"
                    "(If already checked, toggle it off and on.)\n"
                    "Then restart cmdc."
                ),
            )

    def _open_config(self, _):
        subprocess.run(["open", str(config.CONFIG_PATH)])

    def _open_log(self, _):
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.touch(exist_ok=True)
        subprocess.run(["open", str(LOG_PATH)])

    def _open_input_monitoring(self, _):
        subprocess.run([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
        ])

    def _open_accessibility(self, _):
        subprocess.run([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        ])

    # ---------- correction flow ----------

    def _on_hotkey_progress(self, _vk, press_count: int, _target_count: int):
        if not self.cfg["enabled"] or self._busy.locked():
            return
        self.title = f"⌘{press_count}"
        threading.Timer(0.35, self._sync_idle_icon_if_ready).start()

    def _on_triple_copy(self):
        if not self.cfg["enabled"]:
            return
        if not self._busy.acquire(blocking=False):
            return  # already processing
        threading.Thread(target=self._process, daemon=True).start()

    def _process(self):
        try:
            self.title = ICON_BUSY
            time.sleep(0.18)  # let the user's own Cmd+C land on the pasteboard
            text = clipboard.get_text()
            if not text or not text.strip():
                log.warning("clipboard empty, nothing to correct")
                self._flash(ICON_ERR, "Nothing to correct", "Clipboard is empty.")
                return
            if len(text) > self.cfg["max_chars"]:
                log.warning("text too long: %d chars", len(text))
                self._flash(
                    ICON_ERR,
                    "Text too long",
                    f"{len(text)} chars > limit {self.cfg['max_chars']}.",
                )
                return
            log.info("correcting %d chars via %s/%s",
                     len(text), self.cfg["provider"], config.model_for(self.cfg))
            t0 = time.monotonic()
            try:
                fixed = ai.correct(text, self.cfg)
            except ai.AIError as e:
                log.error("correction failed: %s", e)
                self._flash(ICON_ERR, "Correction failed", str(e))
                return
            log.info("API ok in %.1fs, pasting", time.monotonic() - t0)
            fixed = ai.apply_substitutions(fixed, self.cfg)
            clipboard.set_text(fixed)
            time.sleep(0.08)
            clipboard.paste()
            self._flash(ICON_OK)
        finally:
            self._busy.release()

    def _flash(self, icon, note_title=None, note_text=None):
        self.title = icon
        if note_title:
            _notify(note_title, note_text or "")
        threading.Timer(1.5, self._sync_idle_icon).start()


def _notify(title: str, text: str):
    try:
        rumps.notification("cmdc", title, text)
    except Exception:
        # notifications need a proper app bundle on recent macOS; fall back
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{text[:120]}" with title "cmdc: {title}"'],
            check=False,
        )


def _check_permissions() -> bool:
    """Check Input Monitoring and Accessibility without blocking startup.

    pynput gets no events without Input Monitoring. Permission prompts are not
    requested here because their modal UI can block the menu-bar app before
    its event loop starts.
    """
    try:
        from Quartz import (
            CGPreflightListenEventAccess,
            CGPreflightPostEventAccess,
        )
    except ImportError:
        log.warning("Quartz permission APIs unavailable, skipping check")
        return True

    listen = bool(CGPreflightListenEventAccess())
    post = bool(CGPreflightPostEventAccess())
    log.info("permissions: input monitoring=%s, accessibility(post)=%s", listen, post)

    if not (listen and post):
        log.warning(
            "permissions missing; enable cmdc under Privacy & Security, "
            "then restart"
        )
        return False
    return True


def main():
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("CMDC_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(),
        ],
    )
    log.info("cmdc starting (log=%s)", LOG_PATH)
    try:
        from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
        nsapp = NSApplication.sharedApplication()
        nsapp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    except Exception as e:
        log.warning("failed to set activation policy: %s", e)
    CmdCApp(permissions_ok=_check_permissions()).run()


if __name__ == "__main__":
    main()
