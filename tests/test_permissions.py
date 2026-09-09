import copy
import signal
import unittest
from unittest import mock

import Quartz

from cmdc import app
from cmdc import config


class PermissionStartupTests(unittest.TestCase):
    def setUp(self):
        secure_input = mock.patch.object(app, "_secure_input_enabled", return_value=False)
        secure_input.start()
        self.addCleanup(secure_input.stop)
        timer = mock.patch.object(app.rumps, "Timer")
        timer.start()
        self.addCleanup(timer.stop)

    def test_secure_input_blocks_status_despite_granted_permissions_and_recovers(self):
        with (
            mock.patch.object(app.config, "load", return_value=copy.deepcopy(config.DEFAULTS)),
            mock.patch.object(app, "MultiPressListener"),
            mock.patch.object(app, "_secure_input_enabled", return_value=True),
            mock.patch.object(app, "_secure_input_owner", return_value="ChatGPT"),
            mock.patch.object(app.rumps, "alert") as alert,
        ):
            menu_app = app.CmdCApp(permissions_ok=True)
            self.assertEqual(menu_app.title, app.ICON_ERR)
            self.assertIn("Shortcuts blocked", menu_app.item_perm.title)
            menu_app._menu_check_permissions(None)
            self.assertEqual(alert.call_args.kwargs["title"], "Shortcuts blocked by Secure Input")
            self.assertIn("ChatGPT", alert.call_args.kwargs["message"])

        menu_app._refresh_input_status(None)
        self.assertEqual(menu_app.title, app.ICON_IDLE)
        self.assertEqual(menu_app.item_perm.title, "Check Permissions…")

    def test_hotkey_progress_dispatches_ui_update_to_main_thread(self):
        menu_app = object.__new__(app.CmdCApp)
        with mock.patch.object(app.AppHelper, "callAfter") as dispatch:
            menu_app._on_hotkey_progress(8, 1, 3)
        dispatch.assert_called_once_with(menu_app._show_hotkey_progress, 1)

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


class SecureInputUnblockTests(unittest.TestCase):
    def _blocked_app(self, owner="ChatGPT", pid=4242, held_seconds=120):
        menu_app = object.__new__(app.CmdCApp)
        menu_app.secure_input = True
        menu_app.permissions_ok = True
        menu_app._secure_input_pid = pid
        menu_app._secure_input_owner_name = owner
        menu_app._secure_input_since = app.time.time() - held_seconds
        menu_app._refresh_input_status = mock.Mock()
        return menu_app

    def test_status_item_tracks_owner_and_hold_time(self):
        menu_app = self._blocked_app(held_seconds=3 * 3600 + 300)
        self.assertEqual(
            menu_app._secure_item_title(), "Secure Input: ChatGPT · 3h 05m — Unblock…"
        )
        menu_app.secure_input = False
        self.assertEqual(menu_app._secure_item_title(), "Secure Input: clear")

    def test_unblock_quits_owner_after_confirmation(self):
        menu_app = self._blocked_app()
        with (
            mock.patch.object(app.rumps, "alert", return_value=1) as alert,
            mock.patch.object(app.os, "kill") as kill,
            mock.patch.object(app.threading, "Thread") as thread,
        ):
            menu_app._menu_unblock_secure_input(None)

        self.assertIn("Quit ChatGPT", alert.call_args.kwargs["title"])
        kill.assert_called_once_with(4242, signal.SIGTERM)
        thread.assert_called_once()

    def test_unblock_cancelled_leaves_owner_running(self):
        menu_app = self._blocked_app()
        with (
            mock.patch.object(app.rumps, "alert", return_value=0),
            mock.patch.object(app.os, "kill") as kill,
        ):
            menu_app._menu_unblock_secure_input(None)

        kill.assert_not_called()

    def test_password_apps_are_never_quit(self):
        menu_app = self._blocked_app(owner="1Password", pid=99)
        with (
            mock.patch.object(app.rumps, "alert", return_value=1) as alert,
            mock.patch.object(app.os, "kill") as kill,
        ):
            menu_app._menu_unblock_secure_input(None)

        kill.assert_not_called()
        self.assertIn("password", alert.call_args.kwargs["title"].lower())

    def test_unblocked_state_reports_nothing_to_do(self):
        menu_app = self._blocked_app()
        menu_app.secure_input = False
        with (
            mock.patch.object(app.rumps, "alert", return_value=1) as alert,
            mock.patch.object(app.os, "kill") as kill,
        ):
            menu_app._menu_unblock_secure_input(None)

        kill.assert_not_called()
        self.assertEqual(alert.call_args.kwargs["title"], "Secure Input is clear")

    def test_release_watcher_notifies_and_refreshes(self):
        menu_app = self._blocked_app()
        with (
            mock.patch.object(app, "_secure_input_enabled", return_value=False),
            mock.patch.object(app, "_notify") as notify,
            mock.patch.object(app.AppHelper, "callAfter") as dispatch,
        ):
            menu_app._await_unblock("ChatGPT", timeout=1)

        self.assertEqual(notify.call_args.args[0], "Shortcuts unblocked")
        dispatch.assert_called_once_with(menu_app._refresh_input_status)


if __name__ == "__main__":
    unittest.main()
