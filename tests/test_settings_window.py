import copy
import unittest
from unittest.mock import Mock, patch

from cmdc import app, config
from cmdc.settings_window import SettingsWindowController, _clean_model_title


class SettingsWindowTests(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(config.DEFAULTS)
        self.cfg["provider"] = "gemini"
        self.cfg["model"] = "gemini-3.5-flash-lite"
        self.cfg["models"] = {
            "openai": "gpt-5.6-luna",
            "gemini": "gemini-3.5-flash-lite",
            "anthropic": "claude-haiku-4-5-20251001",
        }
        self.cfg["api_keys"] = {"gemini": "AIza-test", "openai": "sk-test"}
        self.cfg["endpoints"] = {"gemini": "https://custom-proxy"}
        self.mock_app = Mock()
        self.mock_app.cfg = self.cfg

    def test_clean_model_title(self):
        self.assertEqual(_clean_model_title("gpt-5.4-mini (Default)"), "gpt-5.4-mini")
        self.assertEqual(_clean_model_title("gemini-3.7-flash"), "gemini-3.7-flash")

    def test_controller_initialization_and_staged_data(self):
        ctrl = SettingsWindowController.alloc().initWithApp_(self.mock_app)
        self.assertEqual(ctrl.app, self.mock_app)
        self.assertIsNone(ctrl.window)

    def test_shortened_menu_contains_provider_settings(self):
        with (
            patch.object(app.config, "load", return_value=copy.deepcopy(self.cfg)),
            patch.object(app, "MultiPressListener"),
            patch.object(app, "_secure_input_enabled", return_value=False),
        ):
            menu_app = app.CmdCApp(permissions_ok=True)

        menu_titles = [item.title for item in menu_app.menu.values() if hasattr(item, "title")]
        self.assertIn("Enabled", menu_titles)
        self.assertIn("Provider Settings…", menu_titles)
        self.assertIn("Correct Clipboard Now", menu_titles)
        # Ensure original menu clutter is removed
        self.assertFalse(any(t.startswith("Model:") for t in menu_titles))
        self.assertFalse(any(t.startswith("Endpoint:") for t in menu_titles))
        self.assertNotIn("Set API Key…", menu_titles)
        self.assertNotIn("Edit Prompt…", menu_titles)

    def test_settings_window_data_interaction(self):
        ctrl = SettingsWindowController.alloc().initWithApp_(self.mock_app)
        ctrl._build_window()
        ctrl._load_from_app_config()

        # Initially Gemini is active
        self.assertEqual(ctrl.current_provider, "gemini")
        self.assertEqual(ctrl.model_field.stringValue(), "gemini-3.5-flash-lite")

        # Switch to OpenAI
        ctrl.prov_popup.selectItemWithTitle_("openai")
        ctrl.providerChanged_(ctrl.prov_popup)
        self.assertEqual(ctrl.current_provider, "openai")
        self.assertEqual(ctrl.model_field.stringValue(), "gpt-5.6-luna")

        # Change OpenAI model in field
        ctrl.model_field.setStringValue_("gpt-5.4")
        ctrl.modelFieldChanged_(ctrl.model_field)

        # Switch back to Gemini: should remember gemini-3.5-flash-lite
        ctrl.prov_popup.selectItemWithTitle_("gemini")
        ctrl.providerChanged_(ctrl.prov_popup)
        self.assertEqual(ctrl.current_provider, "gemini")
        self.assertEqual(ctrl.model_field.stringValue(), "gemini-3.5-flash-lite")

        # Switch to OpenAI again: should remember the edited gpt-5.4
        ctrl.prov_popup.selectItemWithTitle_("openai")
        ctrl.providerChanged_(ctrl.prov_popup)
        self.assertEqual(ctrl.model_field.stringValue(), "gpt-5.4")

        # Save
        with patch("cmdc.config.save") as mock_save:
            ctrl.saveClicked_(ctrl.save_btn)
            mock_save.assert_called_once()

        self.assertEqual(self.mock_app.cfg["provider"], "openai")
        self.assertEqual(self.mock_app.cfg["models"]["openai"], "gpt-5.4")
        self.assertEqual(self.mock_app.cfg["models"]["gemini"], "gemini-3.5-flash-lite")
        self.mock_app._on_settings_saved.assert_called_once()


if __name__ == "__main__":
    unittest.main()
