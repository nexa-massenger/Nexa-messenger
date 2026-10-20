import os
import tempfile
import unittest

from storage import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "test.sqlite3"))
        self.store.ensure(10001)
        self.store.ensure(10002)
        self.store.consent(10001)
        self.store.consent(10002)

    def tearDown(self):
        self.tmp.cleanup()

    def approved(self, uid=10001):
        pid = self.store.add_photo(uid, "fake-file-id")
        self.assertTrue(self.store.claim(pid))
        self.store.publish(pid, "-100123", pid + 100)
        return pid

    def test_add_photo_returns_inserted_id_and_claim_once(self):
        pid = self.store.add_photo(10001, "fake-file-id")
        self.assertGreater(pid, 0)
        self.assertEqual(self.store.photo(pid)["status"], "pending")
        self.assertTrue(self.store.claim(pid))
        self.assertFalse(self.store.claim(pid))

    def test_rating_once_and_not_own_photo(self):
        pid = self.approved()
        self.assertEqual(self.store.rate(pid, 10001, 8)[0], "own")
        result, avg, count = self.store.rate(pid, 10002, 9)
        self.assertEqual((result, avg, count), ("ok", 9.0, 1))
        self.assertEqual(self.store.rate(pid, 10002, 7)[0], "duplicate")

    def test_reports_hide_at_threshold(self):
        pid = self.approved()
        result, count, hidden, _ = self.store.report(pid, 10002, 3)
        self.assertEqual((result, count, hidden), ("ok", 1, False))
        self.store.ensure(10003)
        result, count, hidden, row = self.store.report(pid, 10003, 3)
        self.assertEqual((result, count, hidden), ("ok", 2, False))
        self.store.ensure(10004)
        result, count, hidden, row = self.store.report(pid, 10004, 3)
        self.assertEqual((result, count, hidden), ("ok", 3, True))
        self.assertEqual(row["status"], "hidden")

    def test_delete_cascades_ratings_and_reports(self):
        pid = self.approved()
        self.store.rate(pid, 10002, 10)
        self.store.report(pid, 10002, 3)
        self.assertEqual(self.store.delete_user_photos(10001), 1)
        self.assertIsNone(self.store.photo(pid))
        self.assertEqual(self.store.stats()["ratings"], 0)
        self.assertEqual(self.store.stats()["reports"], 0)


if __name__ == "__main__":
    unittest.main()
