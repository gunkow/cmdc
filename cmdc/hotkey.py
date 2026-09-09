"""Global hotkey detection: N rapid presses of Cmd+<key> -> action.

Designed as a combo->action map so future triggers (e.g. triple Cmd+D
for a custom-prompt window) are one line in ACTIONS.
"""

import logging
import time

from pynput import keyboard
from Quartz import (
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventTapEnable,
    kCGEventFlagMaskCommand,
    kCGEventKeyDown,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    kCGKeyboardEventAutorepeat,
    kCGKeyboardEventKeycode,
)

log = logging.getLogger("cmdc")

# macOS virtual keycodes
VK = {"c": 8, "d": 2}

def _diag_keydown(event):
    """Log key-down details when CMDC_DEBUG is set (proves the tap sees keys)."""
    if not log.isEnabledFor(logging.DEBUG):
        return
    log.debug(
        "diag keydown vk=%s flags=0x%x cmd=%s autorepeat=%s",
        CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode),
        CGEventGetFlags(event),
        bool(CGEventGetFlags(event) & kCGEventFlagMaskCommand),
        CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat),
    )

class _CommandListener(keyboard.Listener):
    """Read modifiers from each event, including after Secure Input gaps."""

    def __init__(self, on_command):
        super().__init__()
        self._on_command = on_command
        self._tap = None

    def _create_event_tap(self):
        self._tap = super()._create_event_tap()
        if self._tap is None:
            log.error("keyboard event tap could not be created; restart after granting permissions")
        return self._tap

    def _handler(self, proxy, event_type, event, refcon):
        # These notifications may have no keyboard event. Handle them before
        # pynput attempts to read event fields, and restore the disabled tap.
        if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            if self._tap is not None:
                CGEventTapEnable(self._tap, True)
                log.warning("keyboard event tap re-enabled after interruption")
            return event
        return super()._handler(proxy, event_type, event, refcon)

    def _handle_message(self, _proxy, event_type, event, _refcon, _injected):
        if event_type != kCGEventKeyDown:
            return
        _diag_keydown(event)
        if not CGEventGetFlags(event) & kCGEventFlagMaskCommand:
            return
        if CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat):
            return
        self._on_command(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))


class MultiPressListener:
    """Fires callbacks when Cmd+<letter> is pressed `count` times within `window` sec."""

    def __init__(
        self,
        actions: dict,
        count: int = 3,
        window: float = 1.0,
        on_progress=None,
    ):
        # actions: {"c": callback, "d": callback}
        self.actions = {VK[k]: cb for k, cb in actions.items()}
        self.count = count
        self.window = window
        self.on_progress = on_progress
        self._times: dict[int, list[float]] = {vk: [] for vk in self.actions}
        self._listener = _CommandListener(self._on_command)

    def start(self):
        self._listener.start()
        log.info("hotkey listener started (Cmd+key x%d within %.1fs)",
                 self.count, self.window)

    def stop(self):
        self._listener.stop()

    def _on_command(self, vk):
        if vk not in self.actions:
            return
        now = time.monotonic()
        times = [t for t in self._times[vk] if now - t <= self.window]
        times.append(now)
        log.info("Cmd press detected (vk=%s) %d/%d", vk, len(times), self.count)
        if self.on_progress:
            self.on_progress(vk, len(times), self.count)
        if len(times) >= self.count:
            self._times[vk] = []
            log.info("trigger fired (vk=%s)", vk)
            self.actions[vk]()
        else:
            self._times[vk] = times
