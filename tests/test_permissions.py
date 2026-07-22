import copy
import unittest
from unittest import mock

import Quartz

from cmdc import app
from cmdc import config


class PermissionStartupTests(unittest.TestCase):
    def test_missing_permissions_do_not_show_modal_alert_before_event_loop(self):
        with (
            mock.patch.object(
                Quartz, "CGPreflightListenEventAccess", return_value=False
            ),
            mock.patch.object(
                Quartz, "CGPreflightPostEventAccess", return_value=False
            ),
            mock.patch.object(Quartz, "CGRequestListenEventAccess") as request_listen,
            mock.patch.object(Quartz, "CGRequestPostEventAccess") as request_post,
            mock.patch.object(app.rumps, "alert") as alert,
            mock.patch.object(app, "_notify") as notify,
        ):
            permitted = app._check_permissions()

        self.assertFalse(permitted)
        request_listen.assert_not_called()
        request_post.assert_not_called()
        alert.assert_not_called()
        notify.assert_not_called()

    def test_missing_permissions_expose_recovery_menu_and_error_icon(self):
        with (
            mock.patch.object(
                app.config, "load", return_value=copy.deepcopy(config.DEFAULTS)
            ),
            mock.patch.object(app, "MultiPressListener"),
        ):
            menu_app = app.CmdCApp(permissions_ok=False)

        self.assertEqual(menu_app.title, app.ICON_ERR)
        self.assertIn("Permissions required", menu_app.menu.keys())

    def test_granted_permissions_hide_recovery_menu(self):
        with (
            mock.patch.object(
                app.config, "load", return_value=copy.deepcopy(config.DEFAULTS)
            ),
            mock.patch.object(app, "MultiPressListener"),
        ):
            menu_app = app.CmdCApp(permissions_ok=True)

        self.assertEqual(menu_app.title, app.ICON_IDLE)
        self.assertNotIn("Permissions required", menu_app.menu.keys())

    def test_permission_menu_opens_both_privacy_panes(self):
        menu_app = object.__new__(app.CmdCApp)
        with mock.patch.object(app.subprocess, "run") as run:
            menu_app._open_input_monitoring(None)
            menu_app._open_accessibility(None)

        self.assertEqual(run.call_count, 2)
        self.assertIn("Privacy_ListenEvent", run.call_args_list[0].args[0][1])
        self.assertIn("Privacy_Accessibility", run.call_args_list[1].args[0][1])


if __name__ == "__main__":
    unittest.main()
