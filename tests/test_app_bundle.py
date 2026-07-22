import ast
import os
import plistlib
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


APP_RECIPE = Path(__file__).parents[1] / "macos" / "setup.py"
TEST_APP_BUNDLE = os.environ.get("CMDC_TEST_APP_BUNDLE")
APP_INFO = (
    Path(TEST_APP_BUNDLE) / "Contents" / "Info.plist"
    if TEST_APP_BUNDLE
    else None
)


def _recipe_assignment(name):
    tree = ast.parse(APP_RECIPE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            matches = (
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets
            )
            if any(matches):
                return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is missing from {APP_RECIPE}")


def _load_recipe():
    setuptools = types.ModuleType("setuptools")
    setuptools.setup = mock.Mock()
    with mock.patch.dict(sys.modules, {"setuptools": setuptools}):
        return runpy.run_path(str(APP_RECIPE))


class AppRecipePolicyTests(unittest.TestCase):
    def test_recipe_builds_an_activatable_menu_bar_app(self):
        options = _load_recipe()["OPTIONS"]
        self.assertTrue(options["plist"].get("LSUIElement"))
        self.assertNotIn("LSBackgroundOnly", options["plist"])

    def test_recipe_collects_packages_that_py2app_cannot_infer(self):
        recipe = _load_recipe()
        options = recipe["OPTIONS"]

        self.assertGreaterEqual(
            set(options["packages"]), {"cmdc", "pynput", "charset_normalizer"}
        )
        self.assertEqual(options["includes"], recipe["MYPYC_SUPPORT_MODULES"])
        if recipe["CHARSET_EXTENSIONS"]:
            self.assertTrue(options["includes"])
        self.assertTrue(
            all(module.endswith("__mypyc") for module in options["includes"])
        )
        self.assertTrue(
            all(path.exists() for path in recipe["MYPYC_SUPPORT_EXTENSIONS"])
        )

    def test_bundle_version_comes_from_project_metadata(self):
        recipe = _load_recipe()
        self.assertEqual(
            recipe["OPTIONS"]["plist"]["CFBundleShortVersionString"],
            recipe["PROJECT"]["version"],
        )
        self.assertEqual(
            recipe["OPTIONS"]["plist"]["CFBundleVersion"],
            recipe["PROJECT"]["version"],
        )

    def test_launcher_does_not_shadow_cmdc_package(self):
        self.assertEqual(
            _recipe_assignment("APP"),
            [{"script": "launcher.py", "dest_base": "cmdc"}],
        )


@unittest.skipUnless(APP_INFO and APP_INFO.exists(), "set CMDC_TEST_APP_BUNDLE")
class BuiltAppPolicyTests(unittest.TestCase):
    def test_menu_bar_app_can_activate_text_entry_dialogs(self):
        with APP_INFO.open("rb") as info_file:
            info = plistlib.load(info_file)

        self.assertTrue(info.get("LSUIElement"))
        self.assertNotIn("LSBackgroundOnly", info)


if __name__ == "__main__":
    unittest.main()
