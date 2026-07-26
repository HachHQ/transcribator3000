import unittest
from datetime import datetime, timedelta, timezone

from app.services.daily_brief import TimeInterval, filter_tasks_by_max_age, find_conflicts, free_windows


class DailyBriefLogicTests(unittest.TestCase):
    def test_find_conflicts(self) -> None:
        base = datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc)
        a = TimeInterval(base, base + timedelta(hours=1), "A")
        b = TimeInterval(base + timedelta(minutes=30), base + timedelta(hours=2), "B")
        c = TimeInterval(base + timedelta(hours=3), base + timedelta(hours=4), "C")
        conflicts = find_conflicts([a, b, c])
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0][0].title, "A")
        self.assertEqual(conflicts[0][1].title, "B")

    def test_free_windows(self) -> None:
        day_start = datetime(2026, 7, 25, 9, 0, tzinfo=timezone.utc)
        day_end = datetime(2026, 7, 25, 18, 0, tzinfo=timezone.utc)
        busy = [
            TimeInterval(
                datetime(2026, 7, 25, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 7, 25, 11, 0, tzinfo=timezone.utc),
                "meeting",
            )
        ]
        windows = free_windows(busy, day_start, day_end, min_minutes=30)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].start, day_start)
        self.assertEqual(windows[0].end, busy[0].start)
        self.assertEqual(windows[1].start, busy[0].end)
        self.assertEqual(windows[1].end, day_end)

    def test_filter_old_tasks(self) -> None:
        now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
        tasks = [
            {"title": "new", "updated": "2026-07-20T10:00:00.000Z"},
            {"title": "old", "updated": "2025-01-01T10:00:00.000Z"},
            {"title": "due-recent", "due": "2026-07-25T00:00:00.000Z", "updated": "2025-01-01T10:00:00.000Z"},
        ]
        kept, skipped = filter_tasks_by_max_age(tasks, now=now, max_age_days=7)
        titles = {t["title"] for t in kept}
        self.assertEqual(titles, {"new", "due-recent"})
        self.assertEqual(skipped, 1)

    def test_filter_disabled(self) -> None:
        now = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
        tasks = [{"title": "old", "updated": "2020-01-01T00:00:00.000Z"}]
        kept, skipped = filter_tasks_by_max_age(tasks, now=now, max_age_days=0)
        self.assertEqual(len(kept), 1)
        self.assertEqual(skipped, 0)


if __name__ == "__main__":
    unittest.main()
