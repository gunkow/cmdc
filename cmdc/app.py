"""Menu bar app: triple Cmd+C -> AI-correct the copied text -> paste in place."""

import logging
import os
import subprocess
import threading
import time

import rumps

log = logging.getLogger("cmdc")

from . import ai, clipboard, config
from .hotkey import MultiPressListener

ICON_IDLE = "⌘C"
ICON_BUSY = "⌘…"
ICON_OK = "⌘✓"
ICON_ERR = "⌘✗"
ICON_OFF = "⌘×"


class CmdCApp(rumps.App):
    def __init__(self):
        super().__init__("cmdc", title=ICON_IDLE, quit_button="Quit")
        self.cfg = config.load()
        self._busy = threading.Lock()
        self._build_menu()
        self._sync_idle_icon()
        self.listener = MultiPressListener(
            actions={"c": self._on_triple_copy},
            count=self.cfg["trigger_count"],
            window=self.cfg["trigger_window_sec"],
        )
        self.listener.start()
        log.info("ready: provider=%s model=%s enabled=%s",
                 self.cfg["provider"], config.model_for(self.cfg),
                 self.cfg["enabled"])

    # ---------- menu ----------

    def _build_menu(self):
        self.item_enabled = rumps.MenuItem("Enabled", callback=self._toggle_enabled)
        self.item_enabled.state = self.cfg["enabled"]

        self.provider_menu = rumps.MenuItem("Provider")
        for name in self.cfg["providers"]:
            item = rumps.MenuItem(name, callback=self._pick_provider)
            item.state = name == self.cfg["provider"]
            self.provider_menu.add(item)

        self.item_model = rumps.MenuItem("", callback=self._edit_model)
        self._refresh_model_title()
        self.item_key = rumps.MenuItem("Set API Key…", callback=self._edit_key)
        self.item_prompt = rumps.MenuItem("Edit Prompt…", callback=self._edit_prompt)

        self.item_subs = rumps.MenuItem(
            "Replace symbols (— “” …)", callback=self._toggle_subs
        )
        self.item_subs.state = self.cfg["substitutions_enabled"]
        self.item_cfg = rumps.MenuItem("Open Config File", callback=self._open_config)

        self.menu = [
            self.item_enabled,
            None,
            self.provider_menu,
            self.item_model,
            self.item_key,
            self.item_prompt,
            None,
            self.item_subs,
            self.item_cfg,
            None,
        ]

    def _refresh_model_title(self):
        self.item_model.title = f"Model: {config.model_for(self.cfg)} …"

    def _sync_idle_icon(self):
        self.title = ICON_IDLE if self.cfg["enabled"] else ICON_OFF

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
            self.cfg["model"] = resp.text.strip()
            self._refresh_model_title()
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
            dimensions=(420, 140),
        )
        resp = win.run()
        if resp.clicked and resp.text.strip():
            self.cfg["system_prompt"] = resp.text.strip()
            config.save(self.cfg)

    def _toggle_subs(self, item):
        self.cfg["substitutions_enabled"] = not self.cfg["substitutions_enabled"]
        item.state = self.cfg["substitutions_enabled"]
        config.save(self.cfg)

    def _open_config(self, _):
        subprocess.run(["open", str(config.CONFIG_PATH)])

    # ---------- correction flow ----------

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
    """Check + actively request Input Monitoring and Accessibility.

    pynput gets NO events without Input Monitoring — silently. The request
    calls pop the system prompt and add the host app (your terminal) to the
    list in System Settings.
    """
    try:
        from Quartz import (
            CGPreflightListenEventAccess,
            CGPreflightPostEventAccess,
            CGRequestListenEventAccess,
            CGRequestPostEventAccess,
        )
    except ImportError:
        log.warning("Quartz permission APIs unavailable, skipping check")
        return True

    listen = bool(CGPreflightListenEventAccess())
    post = bool(CGPreflightPostEventAccess())
    log.info("permissions: input monitoring=%s, accessibility(post)=%s", listen, post)

    if not listen:
        CGRequestListenEventAccess()
    if not post:
        CGRequestPostEventAccess()

    if not (listen and post):
        rumps.alert(
            title="cmdc needs permissions",
            message=(
                "Without these, the triple Cmd+C is never seen.\n\n"
                "System Settings → Privacy & Security:\n"
                "  • Input Monitoring → enable your terminal app\n"
                "  • Accessibility → enable your terminal app\n\n"
                "(If it's already checked, toggle it off and on.)\n"
                "Then QUIT and RESTART cmdc — permissions only apply "
                "to a fresh process."
            ),
        )
        return False
    return True


def main():
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("CMDC_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("cmdc starting")
    _check_permissions()
    CmdCApp().run()


if __name__ == "__main__":
    main()
