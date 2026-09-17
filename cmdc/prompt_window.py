"""Dedicated large system prompt editor window for cmdc."""

import logging

import AppKit
import objc
from Foundation import NSObject, NSMakeRect, NSMakeSize

from . import config

log = logging.getLogger("cmdc")


class PromptWindowController(NSObject):
    def initWithApp_(self, app):
        self = objc.super(PromptWindowController, self).init()
        if self is None:
            return None
        self.app = app
        self.window = None
        return self

    def show(self):
        if self.window is None:
            self._build_window()
        self._load_from_app_config()
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        self.window.makeFirstResponder_(self.text_view)

    def _build_window(self):
        # 760 wide, 560 high - spacious and resizable
        self.window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 760, 560),
            AppKit.NSWindowStyleMaskTitled
            | AppKit.NSWindowStyleMaskClosable
            | AppKit.NSWindowStyleMaskResizable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("cmdc — System Prompt")
        self.window.setMinSize_(NSMakeSize(580, 420))
        self.window.setReleasedWhenClosed_(False)

        content = self.window.contentView()

        # Header
        title = AppKit.NSTextField.labelWithString_("System Prompt")
        title.setFont_(AppKit.NSFont.boldSystemFontOfSize_(15))
        title.setFrame_(NSMakeRect(24, 520, 240, 22))
        title.setAutoresizingMask_(AppKit.NSViewMinYMargin)
        content.addSubview_(title)

        desc = AppKit.NSTextField.labelWithString_(
            "Instructions sent to the AI model alongside your copied text to guide grammar, tone, and formatting."
        )
        desc.setFont_(AppKit.NSFont.systemFontOfSize_(12))
        desc.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        desc.setFrame_(NSMakeRect(24, 496, 712, 18))
        desc.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewMinYMargin)
        content.addSubview_(desc)

        # Main scrollable text area
        scroll = AppKit.NSScrollView.alloc().initWithFrame_(NSMakeRect(24, 60, 712, 424))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setBorderType_(AppKit.NSBezelBorder)
        scroll.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)

        content_size = scroll.contentSize()
        self.text_view = AppKit.NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, content_size.width, content_size.height)
        )
        self.text_view.setMinSize_(NSMakeSize(0.0, content_size.height))
        self.text_view.setMaxSize_(NSMakeSize(1e7, 1e7))
        self.text_view.setVerticallyResizable_(True)
        self.text_view.setHorizontallyResizable_(False)
        self.text_view.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        self.text_view.textContainer().setWidthTracksTextView_(True)
        self.text_view.setFont_(AppKit.NSFont.systemFontOfSize_(13.5))
        self.text_view.setAllowsUndo_(True)
        self.text_view.setRichText_(False)
        self.text_view.setAutomaticQuoteSubstitutionEnabled_(False)
        self.text_view.setDelegate_(self)
        scroll.setDocumentView_(self.text_view)
        content.addSubview_(scroll)

        # Bottom Bar
        self.reset_btn = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(24, 18, 130, 30))
        self.reset_btn.setTitle_("Reset to Default")
        self.reset_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.reset_btn.setAutoresizingMask_(AppKit.NSViewMaxXMargin | AppKit.NSViewMaxYMargin)
        self.reset_btn.setTarget_(self)
        self.reset_btn.setAction_("resetClicked:")
        content.addSubview_(self.reset_btn)

        self.counter_label = AppKit.NSTextField.labelWithString_("0 characters")
        self.counter_label.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        self.counter_label.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        self.counter_label.setFrame_(NSMakeRect(165, 23, 240, 16))
        self.counter_label.setAutoresizingMask_(AppKit.NSViewMaxXMargin | AppKit.NSViewMaxYMargin)
        content.addSubview_(self.counter_label)

        self.cancel_btn = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(546, 16, 90, 32))
        self.cancel_btn.setTitle_("Cancel")
        self.cancel_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.cancel_btn.setAutoresizingMask_(AppKit.NSViewMinXMargin | AppKit.NSViewMaxYMargin)
        self.cancel_btn.setTarget_(self)
        self.cancel_btn.setAction_("cancelClicked:")
        content.addSubview_(self.cancel_btn)

        self.save_btn = AppKit.NSButton.alloc().initWithFrame_(NSMakeRect(646, 16, 90, 32))
        self.save_btn.setTitle_("Save")
        self.save_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.save_btn.setKeyEquivalent_(chr(13))
        self.save_btn.setAutoresizingMask_(AppKit.NSViewMinXMargin | AppKit.NSViewMaxYMargin)
        self.save_btn.setTarget_(self)
        self.save_btn.setAction_("saveClicked:")
        content.addSubview_(self.save_btn)

    def _load_from_app_config(self):
        current_prompt = self.app.cfg.get("system_prompt", config.DEFAULT_PROMPT)
        self.text_view.setString_(current_prompt)
        self._update_counter()

    def _update_counter(self):
        text = str(self.text_view.string())
        chars = len(text)
        words = len(text.split())
        self.counter_label.setStringValue_(f"{chars} characters • {words} words")

    def textDidChange_(self, notification):
        self._update_counter()

    def resetClicked_(self, sender):
        self.text_view.setString_(config.DEFAULT_PROMPT)
        self._update_counter()

    def cancelClicked_(self, sender):
        self.window.orderOut_(None)

    def saveClicked_(self, sender):
        new_prompt = str(self.text_view.string()).strip()
        if new_prompt:
            self.app.cfg["system_prompt"] = new_prompt
            config.save(self.app.cfg)
            self.app._on_settings_saved()
        self.window.orderOut_(None)
