"""Global hotkey detection: N rapid presses of Cmd+<key> -> action.

Designed as a combo->action map so future triggers (e.g. triple Cmd+D
for a custom-prompt window) are one line in ACTIONS.
"""

import logging
import time

from pynput import keyboard

log = logging.getLogger("cmdc")

# macOS virtual keycodes
VK = {"c": 8, "d": 2}

_CMD_KEYS = {
    getattr(keyboard.Key, name)
    for name in ("cmd", "cmd_l", "cmd_r")
    if hasattr(keyboard.Key, name)
}


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
        self._cmd_down = False
        self._times: dict[int, list[float]] = {vk: [] for vk in self.actions}
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )

    def start(self):
        self._listener.start()
        log.info("hotkey listener started (Cmd+key x%d within %.1fs)",
                 self.count, self.window)

    def stop(self):
        self._listener.stop()

    def _on_press(self, key):
        if key in _CMD_KEYS:
            self._cmd_down = True
            return
        if not self._cmd_down:
            return
        vk = getattr(key, "vk", None)
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

    def _on_release(self, key):
        if key in _CMD_KEYS:
            self._cmd_down = False
