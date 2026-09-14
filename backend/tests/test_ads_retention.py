import io
import unittest
from contextlib import redirect_stderr

from app.jobs.ads_retention import (
    INVENTORY_TABLES,
    SALES_TABLES,
    parse_args,
)


class AdsRetentionTests(unittest.TestCase):
    def test_managed_tables_are_explicit_and_disjoint(self) -> None:
        self.assertEqual(len(SALES_TABLES), 19)
        self.assertEqual(len(INVENTORY_TABLES), 7)
        self.assertFalse(set(SALES_TABLES) & set(INVENTORY_TABLES))
        self.assertNotIn("ads_publish_batch", SALES_TABLES + INVENTORY_TABLES)

    def test_apply_defaults_keep_two_ready_versions(self) -> None:
        args = parse_args(["--apply"])
        self.assertTrue(args.apply)
        self.assertEqual(args.keep_ready, 2)
        self.assertEqual(args.chunk_rows, 20_000)

    def test_modes_are_mutually_exclusive(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["--health", "--apply"])


if __name__ == "__main__":
    unittest.main()
