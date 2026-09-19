"""Interactive Settings Window for cmdc (PyObjC Cocoa NSWindow)."""

import copy
import logging
import os
import subprocess
from pathlib import Path

import AppKit
import objc
from Foundation import NSObject, NSMakeRect

from . import config

log = logging.getLogger("cmdc")

PRESET_MODELS = {
    "openai": [
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.6-luna",
        "gpt-5.6",
    ],
    "gemini": [
        "gemini-3.7-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
    ],
    "anthropic": [
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-5-20251101",
    ],
}


def _clean_model_title(title: str) -> str:
    return title.replace(" (Default)", "").strip()


class SettingsWindowController(NSObject):
    def initWithApp_(self, app):
        self = objc.super(SettingsWindowController, self).init()
        if self is None:
            return None
        self.app = app
        self.window = None
        self.current_provider = "openai"
        self.staged = {}
        return self

    def show(self):
        if self.window is None:
            self._build_window()
        self._load_from_app_config()
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)

    def _build_window(self):
        self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 540, 530),
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("cmdc — Provider Settings")
        self.window.setReleasedWhenClosed_(False)

        content = self.window.contentView()

        # Top bar: Active Provider
        lbl_prov = AppKit.NSTextField.labelWithString_("Active Provider:")
        lbl_prov.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        lbl_prov.setFrame_(NSMakeRect(24, 484, 120, 20))
        content.addSubview_(lbl_prov)

        self.prov_popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(144, 480, 180, 26), False
        )
        self.prov_popup.setTarget_(self)
        self.prov_popup.setAction_("providerChanged:")
        content.addSubview_(self.prov_popup)

        lbl_hint = AppKit.NSTextField.labelWithString_("Active correction engine")
        lbl_hint.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        lbl_hint.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        lbl_hint.setFrame_(NSMakeRect(336, 484, 180, 18))
        content.addSubview_(lbl_hint)

        # Provider Settings Box
        self.prov_box = AppKit.NSBox.alloc().initWithFrame_(NSMakeRect(20, 140, 500, 325))
        self.prov_box.setTitle_("Provider Settings")
        content.addSubview_(self.prov_box)

        box_view = self.prov_box.contentView()

        # Model row
        lbl_model = AppKit.NSTextField.labelWithString_("Model:")
        lbl_model.setFrame_(NSMakeRect(16, 262, 85, 20))
        box_view.addSubview_(lbl_model)

        self.model_popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(105, 260, 210, 26), False
        )
        self.model_popup.setTarget_(self)
        self.model_popup.setAction_("modelPresetChanged:")
        box_view.addSubview_(self.model_popup)

        self.model_field = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(325, 262, 155, 22)
        )
        self.model_field.setTarget_(self)
        self.model_field.setAction_("modelFieldChanged:")
        box_view.addSubview_(self.model_field)

        # API Key row
        lbl_key = AppKit.NSTextField.labelWithString_("API Key:")
        lbl_key.setFrame_(NSMakeRect(16, 210, 85, 20))
        box_view.addSubview_(lbl_key)

        self.key_field = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(105, 209, 375, 22)
        )
        box_view.addSubview_(self.key_field)

        self.key_hint = AppKit.NSTextField.labelWithString_("")
        self.key_hint.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        self.key_hint.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        self.key_hint.setFrame_(NSMakeRect(105, 190, 375, 16))
        box_view.addSubview_(self.key_hint)

        # Endpoint row
        lbl_ep = AppKit.NSTextField.labelWithString_("Endpoint URL:")
        lbl_ep.setFrame_(NSMakeRect(16, 146, 85, 20))
        box_view.addSubview_(lbl_ep)

        self.endpoint_field = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(105, 145, 375, 22)
        )
        box_view.addSubview_(self.endpoint_field)

        self.endpoint_hint = AppKit.NSTextField.labelWithString_("")
        self.endpoint_hint.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        self.endpoint_hint.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        self.endpoint_hint.setFrame_(NSMakeRect(105, 126, 375, 16))
        box_view.addSubview_(self.endpoint_hint)

        # Thinking Level row
        self.thinking_label = AppKit.NSTextField.labelWithString_("Thinking Level:")
        self.thinking_label.setFrame_(NSMakeRect(16, 80, 95, 20))
        box_view.addSubview_(self.thinking_label)

        self.thinking_popup = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(115, 78, 140, 26), False
        )
        self.thinking_popup.addItemsWithTitles_(["minimal", "low", "medium", "high"])
        self.thinking_popup.setTarget_(self)
        self.thinking_popup.setAction_("thinkingChanged:")
        box_view.addSubview_(self.thinking_popup)

        self.thinking_hint = AppKit.NSTextField.labelWithString_("minimal for 3.5, low for 3.7")
        self.thinking_hint.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        self.thinking_hint.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        self.thinking_hint.setFrame_(NSMakeRect(265, 82, 200, 16))
        box_view.addSubview_(self.thinking_hint)

        # Files buttons
        btn_cfg = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(16, 20, 130, 28))
        btn_cfg.setTitle_("Open Config File")
        btn_cfg.setBezelStyle_(AppKit.NSBezelStyleRounded)
        btn_cfg.setTarget_(self)
        btn_cfg.setAction_("openConfigClicked:")
        box_view.addSubview_(btn_cfg)

        btn_log = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(152, 20, 120, 28))
        btn_log.setTitle_("Open Log File")
        btn_log.setBezelStyle_(AppKit.NSBezelStyleRounded)
        btn_log.setTarget_(self)
        btn_log.setAction_("openLogClicked:")
        box_view.addSubview_(btn_log)

        # Correction Behavior Box
        self.behavior_box = AppKit.NSBox.alloc().initWithFrame_(NSMakeRect(20, 64, 500, 62))
        self.behavior_box.setTitle_("Correction Behavior")
        content.addSubview_(self.behavior_box)

        cbox_view = self.behavior_box.contentView()

        self.subs_checkbox = AppKit.NSButton.checkboxWithTitle_target_action_(
            "Replace typographic symbols (— → -, “” → "", … → ...)", self, "subsToggled:"
        )
        self.subs_checkbox.setFrame_(NSMakeRect(16, 12, 460, 22))
        cbox_view.addSubview_(self.subs_checkbox)

        # Bottom buttons
        self.cancel_btn = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(330, 16, 84, 32))
        self.cancel_btn.setTitle_("Cancel")
        self.cancel_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.cancel_btn.setTarget_(self)
        self.cancel_btn.setAction_("cancelClicked:")
        content.addSubview_(self.cancel_btn)

        self.save_btn = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(426, 16, 94, 32))
        self.save_btn.setTitle_("Save Settings")
        self.save_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.save_btn.setKeyEquivalent_(chr(13))
        self.save_btn.setTarget_(self)
        self.save_btn.setAction_("saveClicked:")
        content.addSubview_(self.save_btn)

    def _load_from_app_config(self):
        cfg = self.app.cfg
        self.staged = {}
        for prov in cfg.get("providers", {}):
            m = config.model_for(cfg, prov)
            k = cfg.get("api_keys", {}).get(prov, "")
            ep = cfg.get("endpoints", {}).get(prov, "")
            thinking = "low"
            if prov == "gemini":
                body = cfg.get("providers", {}).get("gemini", {}).get("body", {})
                gc = body.get("generationConfig", {})
                tc = gc.get("thinkingConfig", {})
                if isinstance(tc, dict):
                    thinking = tc.get("thinkingLevel", "low")
            self.staged[prov] = {
                "model": m,
                "key": k,
                "endpoint": ep,
                "thinking_level": thinking,
            }

        active_prov = cfg.get("provider", "openai")
        if active_prov not in self.staged:
            self.staged[active_prov] = {
                "model": config.model_for(cfg, active_prov),
                "key": cfg.get("api_keys", {}).get(active_prov, ""),
                "endpoint": cfg.get("endpoints", {}).get(active_prov, ""),
                "thinking_level": "low",
            }

        self.prov_popup.removeAllItems()
        self.prov_popup.addItemsWithTitles_(list(self.staged.keys()))
        self.prov_popup.selectItemWithTitle_(active_prov)
        self.current_provider = active_prov

        subs_enabled = cfg.get("substitutions_enabled", True)
        self.subs_checkbox.setState_(
            AppKit.NSControlStateValueOn if subs_enabled else AppKit.NSControlStateValueOff
        )

        self._display_provider(active_prov)

    def _save_current_provider_inputs(self):
        if self.current_provider not in self.staged:
            return
        model_val = str(self.model_field.stringValue()).strip()
        if not model_val:
            model_val = config.model_for(self.app.cfg, self.current_provider)
        self.staged[self.current_provider]["model"] = model_val
        self.staged[self.current_provider]["key"] = str(self.key_field.stringValue()).strip()
        self.staged[self.current_provider]["endpoint"] = str(self.endpoint_field.stringValue()).strip()
        if self.current_provider == "gemini":
            self.staged[self.current_provider]["thinking_level"] = str(
                self.thinking_popup.titleOfSelectedItem() or "low"
            )

    def _display_provider(self, prov: str):
        self.prov_box.setTitle_(f"{prov.capitalize()} Settings")
        staged_data = self.staged.get(prov, {})
        current_model = staged_data.get("model", "")

        # Model presets
        presets = PRESET_MODELS.get(prov, [])
        default_m = self.app.cfg.get("providers", {}).get(prov, {}).get("default_model", "")
        items = []
        for m in presets:
            if m == default_m:
                items.append(f"{m} (Default)")
            else:
                items.append(m)
        items.append("Custom…")
        self.model_popup.removeAllItems()
        self.model_popup.addItemsWithTitles_(items)

        matched = False
        for it in items:
            if _clean_model_title(it) == current_model:
                self.model_popup.selectItemWithTitle_(it)
                matched = True
                break
        if not matched:
            self.model_popup.selectItemWithTitle_("Custom…")

        self.model_field.setStringValue_(current_model)

        # API Key
        self.key_field.setStringValue_(staged_data.get("key", ""))
        env_var = self.app.cfg.get("providers", {}).get(prov, {}).get("api_key_env", "")
        if env_var:
            self.key_hint.setStringValue_(f"Leave empty to use ${env_var} from environment")
        else:
            self.key_hint.setStringValue_("Stored in ~/.config/cmdc/config.json")

        # Endpoint
        self.endpoint_field.setStringValue_(staged_data.get("endpoint", ""))
        def_ep = self.app.cfg.get("providers", {}).get(prov, {}).get("default_endpoint", "")
        if def_ep:
            self.endpoint_hint.setStringValue_(f"Default: {def_ep} (leave empty for default)")
        else:
            self.endpoint_hint.setStringValue_("Leave empty for default base URL")

        # Thinking Level (Gemini only)
        is_gemini = (prov == "gemini")
        self.thinking_label.setHidden_(not is_gemini)
        self.thinking_popup.setHidden_(not is_gemini)
        self.thinking_hint.setHidden_(not is_gemini)
        if is_gemini:
            level = staged_data.get("thinking_level", "low")
            self.thinking_popup.selectItemWithTitle_(level)

    def providerChanged_(self, sender):
        self._save_current_provider_inputs()
        new_prov = sender.titleOfSelectedItem()
        self.current_provider = new_prov
        self._display_provider(new_prov)

    def modelPresetChanged_(self, sender):
        selected = sender.titleOfSelectedItem()
        if selected == "Custom…":
            self.window.makeFirstResponder_(self.model_field)
            self.model_field.selectText_(None)
        else:
            cleaned = _clean_model_title(selected)
            self.model_field.setStringValue_(cleaned)
            if self.current_provider in self.staged:
                self.staged[self.current_provider]["model"] = cleaned

    def modelFieldChanged_(self, sender):
        val = str(sender.stringValue()).strip()
        if self.current_provider in self.staged:
            self.staged[self.current_provider]["model"] = val
        matched = False
        for it in self.model_popup.itemTitles():
            if _clean_model_title(it) == val:
                self.model_popup.selectItemWithTitle_(it)
                matched = True
                break
        if not matched:
            self.model_popup.selectItemWithTitle_("Custom…")

    def thinkingChanged_(self, sender):
        if self.current_provider == "gemini" and "gemini" in self.staged:
            self.staged["gemini"]["thinking_level"] = sender.titleOfSelectedItem()

    def subsToggled_(self, sender):
        pass

    def openConfigClicked_(self, sender):
        if self.app:
            self.app._open_config(None)

    def openLogClicked_(self, sender):
        if self.app:
            self.app._open_log(None)

    def cancelClicked_(self, sender):
        self.window.orderOut_(None)

    def saveClicked_(self, sender):
        self._save_current_provider_inputs()
        active_prov = self.prov_popup.titleOfSelectedItem()
        self.app.cfg["provider"] = active_prov
        self.app.cfg.setdefault("models", {})
        self.app.cfg.setdefault("api_keys", {})
        self.app.cfg.setdefault("endpoints", {})

        for prov, data in self.staged.items():
            self.app.cfg["models"][prov] = data["model"]
            self.app.cfg["api_keys"][prov] = data["key"]
            self.app.cfg["endpoints"][prov] = data["endpoint"]
            if prov == "gemini":
                gem = self.app.cfg.get("providers", {}).get("gemini", {})
                gc = gem.get("body", {}).get("generationConfig", {})
                if isinstance(gc, dict) and "thinkingConfig" in gc and isinstance(gc["thinkingConfig"], dict):
                    gc["thinkingConfig"]["thinkingLevel"] = data.get("thinking_level", "low")

        self.app.cfg["model"] = self.app.cfg["models"].get(active_prov, "")
        self.app.cfg["substitutions_enabled"] = bool(
            self.subs_checkbox.state() == AppKit.NSControlStateValueOn
        )

        config.save(self.app.cfg)
        self.window.orderOut_(None)
        self.app._on_settings_saved()
