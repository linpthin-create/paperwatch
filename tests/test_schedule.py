import tempfile
import unittest
from pathlib import Path
from unittest import mock

from paperwatch.config import DEFAULT_CONFIG, load_settings
from paperwatch.schedule import build_launchd_plist, schedule_status


class ScheduleTest(unittest.TestCase):
    def test_build_launchd_plist_uses_current_config_and_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(
                DEFAULT_CONFIG.replace("enabled = false", "enabled = true", 1)
                .replace("hour = 12", "hour = 8")
                .replace("minute = 30", "minute = 45"),
                encoding="utf-8",
            )
            settings = load_settings(config)
            with mock.patch("paperwatch.schedule.Path.home", return_value=Path(tmp)):
                plist = build_launchd_plist(config, settings)
        self.assertIn(str(config.resolve()), plist["ProgramArguments"])
        self.assertIn("paperwatch", plist["ProgramArguments"])
        self.assertEqual(plist["StartCalendarInterval"]["Hour"], 8)
        self.assertEqual(plist["StartCalendarInterval"]["Minute"], 45)
        self.assertEqual(plist["WorkingDirectory"], str(config.parent.resolve()))

    def test_schedule_status_reports_feishu_send_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.toml"
            config.write_text(
                DEFAULT_CONFIG.replace("[feishu]\nenabled = false", "[feishu]\nenabled = true")
                .replace('webhook_url = ""', 'webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"', 1),
                encoding="utf-8",
            )
            settings = load_settings(config)
            with mock.patch("paperwatch.schedule.launchd_plist_path", return_value=Path(tmp) / "job.plist"):
                status = schedule_status(config, settings)
        self.assertTrue(status["send_feishu"])
        self.assertFalse(status["installed"])


if __name__ == "__main__":
    unittest.main()
