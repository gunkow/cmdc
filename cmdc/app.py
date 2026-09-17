"""Menu bar app: triple Cmd+C -> AI-correct the copied text -> paste in place."""

import ctypes
import logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import rumps
from Foundation import NSObject
from PyObjCTools import AppHelper

log = logging.getLogger("cmdc")

from . import ai, clipboard, config
from .hotkey import MultiPressListener

ICON_IDLE = "⌘C"
ICON_BUSY = "⌘…"
ICON_OK = "⌘✓"
ICON_ERR = "⌘✗"
ICON_OFF = "⌘×"
LOG_PATH = Path(os.environ.get("CMDC_LOG_PATH", "/tmp/cmdc.log"))


def _secure_input_enabled() -> bool:
    carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
    return bool(carbon.IsSecureEventInputEnabled())


def _secure_input_owner() -> str:
    return _secure_input_owner_info()[1]


def _secure_input_owner_info() -> tuple[int | None, str]:
    """Return (pid, name) of the process holding Secure Input, if known."""
    from AppKit import NSRunningApplication
    from Quartz import CGSessionCopyCurrentDictionary

    session = CGSessionCopyCurrentDictionary() or {}
    pid = session.get("kCGSSessionSecureInputPID")
    if not pid:
        return None, "another app"
    owner = NSRunningApplication.runningApplicationWithProcessIdentifier_(int(pid))
    return int(pid), str(owner.localizedName()) if owner else "another app"


# Owners that legitimately hold Secure Input while collecting a password.
# Quitting these can lose credentials the user is entering, so they are never
# offered as a one-click unblock target.
SENSITIVE_OWNERS = (
    "loginwindow",
    "SecurityAgent",
    "Keychain Access",
    "1Password",
    "Bitwarden",
    "Screen Sharing",
    "Terminal",
    "iTerm",
    "Ghostty",
)


def _is_sensitive_owner(name: str) -> bool:
    lowered = (name or "").lower()
    return any(s.lower() in lowered for s in SENSITIVE_OWNERS)


def _format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


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
        self.secure_input = _secure_input_enabled()
        self._secure_input_pid, self._secure_input_owner_name = (
            _secure_input_owner_info() if self.secure_input else (None, "")
        )
        self._secure_input_since = time.time() if self.secure_input else None
        self.cfg = config.load()
        self._busy = threading.Lock()
        self._settings_controller = None
        self._build_menu()
        self._sync_idle_icon()
        self.listener = MultiPressListener(
            actions={"c": self._on_triple_copy},
            count=self.cfg["trigger_count"],
            window=self.cfg["trigger_window_sec"],
            on_progress=self._on_hotkey_progress,
        )
        self.listener.start()
        log.info(
            "startup state: secure_input=%s permissions_ok=%s icon=%s",
            self.secure_input, self.permissions_ok, self.title,
        )
        self._status_polls = 0
        self._status_thread = None
        log.info("ready: provider=%s model=%s enabled=%s",
                 self.cfg["provider"], config.model_for(self.cfg),
                 self.cfg["enabled"])

    def run(self, **kwargs):
        """Start the event loop, then the Secure Input poller.

        The poller runs only under a live event loop, so it is started here
        instead of in __init__.
        """
        self._status_thread = threading.Thread(
            target=self._poll_input_status, daemon=True, name="cmdc-status-poll"
        )
        self._status_thread.start()
        super().run(**kwargs)

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

        self.item_settings = rumps.MenuItem(
            "Provider Settings…", callback=self._open_settings
        )
        self.item_secure = rumps.MenuItem(
            self._secure_item_title(), callback=self._menu_unblock_secure_input
        )
        self.item_perm = rumps.MenuItem(
            self._perm_item_title(),
            callback=self._menu_check_permissions,
        )
        self.item_fix_clipboard = rumps.MenuItem(
            "Correct Clipboard Now", callback=self._menu_correct_clipboard
        )
        self.item_cfg = rumps.MenuItem("Open Config File", callback=self._open_config)
        self.item_log = rumps.MenuItem("Open Log File", callback=self._open_log)

        menu = [self.item_enabled]
        if not self.permissions_ok:
            menu.append(self.permissions_menu)
        menu.extend([
            None,
            self.item_settings,
            self.item_fix_clipboard,
            None,
            self.item_secure,
            self.item_perm,
            None,
        ])
        self.menu = menu

    def _open_settings(self, _=None):
        if self._settings_controller is None:
            from .settings_window import SettingsWindowController
            self._settings_controller = SettingsWindowController.alloc().initWithApp_(self)
        self._settings_controller.show()

    def _on_settings_saved(self):
        log.info("settings saved: provider=%s model=%s prompt_chars=%d subs=%s",
                 self.cfg["provider"], config.model_for(self.cfg),
                 len(self.cfg.get("system_prompt", "")),
                 self.cfg.get("substitutions_enabled"))
        self._sync_idle_icon()

    def _refresh_model_title(self):
        pass

    def _refresh_endpoint_title(self):
        pass

    def _sync_idle_icon(self):
        if not self.permissions_ok or self.secure_input:
            self.title = ICON_ERR
        else:
            self.title = ICON_IDLE if self.cfg["enabled"] else ICON_OFF

    def _sync_idle_icon_if_ready(self):
        if not self._busy.locked():
            self._sync_idle_icon()

    def _poll_input_status(self):
        """Poll Secure Input from a plain thread.

        A rumps/NSTimer scheduled before the app event loop starts can silently
        never fire, which used to leave the menu bar stuck on the blocked icon
        after Secure Input was released.
        """
        while True:
            try:
                AppHelper.callAfter(self._refresh_input_status)
            except Exception as e:  # pragma: no cover - defensive
                log.warning("status poll dispatch failed: %s", e)
            time.sleep(1)

    def _perm_item_title(self) -> str:
        if not self.secure_input:
            return "Check Permissions…"
        owner = self._secure_input_owner_name
        return f"Shortcuts blocked: Secure Input ({owner})…"

    def _secure_item_title(self) -> str:
        if not self.secure_input:
            return "Secure Input: clear"
        held = _format_duration(time.time() - (self._secure_input_since or time.time()))
        return f"Secure Input: {self._secure_input_owner_name} · {held} — Unblock…"

    def _refresh_input_status(self, _=None):
        secure_input = _secure_input_enabled()
        changed = secure_input != self.secure_input
        self.secure_input = secure_input
        self._status_polls += 1
        if self._status_polls <= 3:
            log.info("input status poll #%d: secure_input=%s", self._status_polls, secure_input)
        if secure_input and (changed or self._status_polls == 1):
            self._secure_input_pid, self._secure_input_owner_name = _secure_input_owner_info()
            if self._secure_input_since is None:
                self._secure_input_since = time.time()
        elif not secure_input:
            self._secure_input_owner_name = ""
            self._secure_input_pid = None
            self._secure_input_since = None
        if changed:
            if secure_input:
                log.info("Secure Input enabled by %s; shortcuts blocked",
                         self._secure_input_owner_name)
                _notify(
                    "Shortcuts blocked",
                    f"Secure Input is held by {self._secure_input_owner_name}. "
                    "Use 'Correct Clipboard Now' meanwhile.",
                )
            else:
                log.info("Secure Input disabled; shortcuts available")
        self.item_perm.title = self._perm_item_title()
        self.item_secure.title = self._secure_item_title()
        self._sync_idle_icon_if_ready()

    def _set_icon(self, icon):
        self.title = icon

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

    def _menu_unblock_secure_input(self, _):
        """Show who holds Secure Input and offer to quit that process."""
        self._refresh_input_status(None)
        if not self.secure_input:
            rumps.alert(
                title="Secure Input is clear",
                message="Nothing is blocking global shortcuts. Triple Cmd+C should work.",
            )
            return

        pid = self._secure_input_pid
        owner = self._secure_input_owner_name or "another app"
        held = _format_duration(time.time() - (self._secure_input_since or time.time()))

        if pid is None:
            rumps.alert(
                title="Secure Input holder unknown",
                message=(
                    "macOS reports Secure Input as active but does not name the owner.\n\n"
                    "Leave any password field, or lock the screen (Ctrl+Cmd+Q) and unlock."
                ),
            )
            return

        if _is_sensitive_owner(owner):
            rumps.alert(
                title=f"{owner} may be collecting a password",
                message=(
                    f"{owner} (pid {pid}) has held Secure Input for at least {held}.\n\n"
                    "cmdc will not quit password-related apps for you: you could lose "
                    "credentials you are typing. Finish or dismiss the password prompt, "
                    "then Secure Input clears on its own."
                ),
            )
            return

        clicked = rumps.alert(
            title=f"Quit {owner} to unblock shortcuts?",
            message=(
                f"{owner} (pid {pid}) has held Secure Input for at least {held}, which blocks "
                "keyboard shortcuts in every app, not just cmdc.\n\n"
                "cmdc will ask it to quit normally (SIGTERM). Save your work there first. "
                "Locking the screen with Ctrl+Cmd+Q and unlocking sometimes clears it "
                "without quitting anything."
            ),
            ok=f"Quit {owner}",
            cancel="Cancel",
        )
        if not clicked:
            return

        log.info("unblock requested: sending SIGTERM to %s (pid %s)", owner, pid)
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError) as e:
            log.error("could not quit %s (pid %s): %s", owner, pid, e)
            rumps.alert(title=f"Could not quit {owner}", message=str(e))
            return
        threading.Thread(
            target=self._await_unblock, args=(owner,), daemon=True
        ).start()

    def _await_unblock(self, owner: str, timeout: float = 10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _secure_input_enabled():
                log.info("Secure Input released after quitting %s", owner)
                _notify("Shortcuts unblocked", f"{owner} released Secure Input.")
                AppHelper.callAfter(self._refresh_input_status)
                return
            time.sleep(0.5)
        log.warning("Secure Input still held %.0fs after quitting %s", timeout, owner)
        _notify(
            "Still blocked",
            f"{owner} quit but Secure Input is still on. Try locking the screen "
            "(Ctrl+Cmd+Q) and unlocking.",
        )
        AppHelper.callAfter(self._refresh_input_status)

    def _menu_check_permissions(self, _):
        self._refresh_input_status(None)
        if self.secure_input:
            rumps.alert(
                title="Shortcuts blocked by Secure Input",
                message=(
                    f"macOS Secure Input is enabled by {_secure_input_owner()} and blocks global "
                    "keyboard shortcuts even when permissions are granted.\n\n"
                    "Leave any password field or close the password dialog. If this "
                    "persists, quit and reopen the app holding Secure Input "
                    "(often a browser, terminal, or Slack).\n\n"
                    "The 'Secure Input: …' menu item shows the holder and can quit it "
                    "for you.\n\n"
                    "cmdc will resume automatically when Secure Input is released."
                ),
            )
            return
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
        AppHelper.callAfter(self._show_hotkey_progress, press_count)

    def _show_hotkey_progress(self, press_count):
        if not self.cfg["enabled"] or self._busy.locked():
            return
        self.title = f"⌘{press_count}"
        AppHelper.callLater(0.35, self._sync_idle_icon_if_ready)

    def _on_triple_copy(self):
        if not self.cfg["enabled"]:
            return
        if not self._busy.acquire(blocking=False):
            return  # already processing
        threading.Thread(target=self._process, daemon=True).start()

    def _menu_correct_clipboard(self, _):
        """Run the correction pipeline from the menu.

        Menu clicks still work while Secure Input blocks the global shortcut,
        so this is the fallback path when another app holds Secure Input.
        """
        if not self._busy.acquire(blocking=False):
            return
        threading.Thread(
            target=self._process, kwargs={"copy_delay": 0.0}, daemon=True
        ).start()

    def _process(self, copy_delay: float = 0.18):
        try:
            AppHelper.callAfter(self._set_icon, ICON_BUSY)
            if copy_delay:
                time.sleep(copy_delay)  # let the user's own Cmd+C land on the pasteboard
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
            fixed = ai.apply_substitutions(fixed, self.cfg)
            clipboard.set_text(fixed)
            if self.secure_input:
                log.info("API ok in %.1fs; Secure Input on, not pasting",
                         time.monotonic() - t0)
                self._flash(
                    ICON_OK,
                    "Corrected text copied",
                    "Secure Input blocks auto-paste; press Cmd+V yourself.",
                )
            else:
                log.info("API ok in %.1fs, pasting", time.monotonic() - t0)
                time.sleep(0.08)
                clipboard.paste()
                self._flash(ICON_OK)
        finally:
            self._busy.release()

    def _flash(self, icon, note_title=None, note_text=None):
        AppHelper.callAfter(self._show_flash, icon, note_title, note_text)

    def _show_flash(self, icon, note_title=None, note_text=None):
        self.title = icon
        if note_title:
            _notify(note_title, note_text or "")
        AppHelper.callLater(1.5, self._sync_idle_icon_if_ready)


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
