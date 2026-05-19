import argparse
import unittest
from datetime import date
from unittest.mock import patch

import paperwatch.main as main_mod


class DateRangeTest(unittest.TestCase):
    def test_explicit_date_range(self):
        args = argparse.Namespace(start_date="2026-05-01", end_date="2026-05-03", days=1)
        self.assertEqual(
            main_mod._resolve_date_range(args),
            (date(2026, 5, 1), date(2026, 5, 3)),
        )

    def test_days_end_yesterday(self):
        args = argparse.Namespace(start_date=None, end_date=None, days=1)
        with patch.object(main_mod, "date") as fake_date:
            fake_date.today.return_value = date(2026, 5, 8)
            fake_date.fromisoformat.side_effect = date.fromisoformat
            self.assertEqual(
                main_mod._resolve_date_range(args),
                (date(2026, 5, 7), date(2026, 5, 7)),
            )

    def test_manual_timestamped_limit_defaults_to_unlimited(self):
        args = argparse.Namespace(limit=None, timestamped=True)
        settings = argparse.Namespace(per_interest_limit=10)
        self.assertIsNone(main_mod._resolve_limit(args, settings))

    def test_scheduled_limit_defaults_to_config(self):
        args = argparse.Namespace(limit=None, timestamped=False)
        settings = argparse.Namespace(per_interest_limit=10)
        self.assertEqual(main_mod._resolve_limit(args, settings), 10)


if __name__ == "__main__":
    unittest.main()
