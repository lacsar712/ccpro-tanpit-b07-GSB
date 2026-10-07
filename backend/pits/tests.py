import os
import tempfile
import threading
from datetime import timedelta

os.environ.setdefault("NINJA_SKIP_REGISTRY", "1")

# Django 5.1 的 SQLite 测试库默认是内存共享缓存，其共享缓存写冲突直接报
# SQLITE_LOCKED，无法模拟真实等待；并发用例改用 WAL 文件库。
if not os.environ.get("DATABASE_URL", "").startswith("postgres"):
    from django.db import connections

    connections.databases  # 触发 TEST 默认键（MIRROR 等）填充
    connections.databases["default"]["TEST"]["NAME"] = os.path.join(
        tempfile.gettempdir(), "tanpit_test_conc.db"
    )

from django.db import connection
from django.db.backends.signals import connection_created
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from ninja.testing import TestClient

from pits.api import api, seven_day_window
from pits.auth import make_token
from pits.models import DrainEvent, LiquorSample, Pit, User, Yard


def _enable_sqlite_busy_timeout(sender, connection, **kwargs):
    # 并发用：两个线程写同一库时开 WAL + 等待锁，让后来者等先提交者落盘后，
    # 再按最新已提交值重新评估条件更新（而不是立刻 database is locked）。
    if connection.vendor == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=20000")


connection_created.connect(_enable_sqlite_busy_timeout)


class BoardTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="worker1", role="worker")
        self.user.set_password("123456")
        self.user.save()
        self.token = make_token(self.user.username)
        self.client = TestClient(api, headers={"Authorization": f"Bearer {self.token}"})
        self.yard = Yard.objects.create(name="南冈鞣场", village="青皮村")

    def pit(self, code, status=Pit.STATUS_TANNING, ph=4.2):
        p = Pit.objects.create(yard=self.yard, code=code, status=status, row=0, col=0)
        if ph is not None:
            LiquorSample.objects.create(pit=p, ph=ph, operator="worker1")
        return p

    def seven_day(self):
        return self.client.get("/drains/seven-day").json()


class DrainEventTests(BoardTestBase):
    def test_successful_drain_creates_exactly_one_event(self):
        p = self.pit("东-1")
        resp = self.client.post(f"/pits/{p.id}/status", json={"status": "drained"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "drained")
        events = DrainEvent.objects.filter(pit=p)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().operator, "worker1")
        self.assertEqual(self.seven_day()["count"], 1)

    def test_repeated_drained_does_not_double_count(self):
        p = self.pit("东-1")
        self.assertEqual(self.client.post(f"/pits/{p.id}/status", json={"status": "drained"}).status_code, 200)
        resp = self.client.post(f"/pits/{p.id}/status", json={"status": "drained"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(DrainEvent.objects.filter(pit=p).count(), 1)
        self.assertEqual(self.seven_day()["count"], 1)

    def test_redrain_after_reset_counts_new_success(self):
        p = self.pit("东-1")
        self.client.post(f"/pits/{p.id}/status", json={"status": "drained"})
        self.client.post(f"/pits/{p.id}/status", json={"status": "tanning"})
        self.client.post(f"/pits/{p.id}/status", json={"status": "drained"})
        self.assertEqual(DrainEvent.objects.filter(pit=p).count(), 2)
        self.assertEqual(self.seven_day()["count"], 2)

    def test_non_drain_transitions_create_no_event(self):
        p = self.pit("东-1", status=Pit.STATUS_FILL)
        resp = self.client.post(f"/pits/{p.id}/status", json={"status": "tanning"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(DrainEvent.objects.count(), 0)
        self.assertEqual(self.seven_day()["count"], 0)

    def test_failed_rule_creates_no_event(self):
        p = self.pit("东-1", ph=6.1)  # 酸碱不达标，规则拒绝放液
        resp = self.client.post(f"/pits/{p.id}/status", json={"status": "drained"})
        self.assertEqual(resp.status_code, 400)
        p.refresh_from_db()
        self.assertEqual(p.status, Pit.STATUS_TANNING)
        self.assertEqual(DrainEvent.objects.count(), 0)
        self.assertEqual(self.seven_day()["count"], 0)

    def test_drain_without_sample_is_rejected(self):
        p = self.pit("东-1", ph=None)
        resp = self.client.post(f"/pits/{p.id}/status", json={"status": "drained"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(DrainEvent.objects.count(), 0)


class SevenDayWindowTests(BoardTestBase):
    def _event(self, p, when):
        return DrainEvent.objects.create(pit=p, drained_at=when, operator="worker1")

    def test_window_is_server_calendar_last_seven_days(self):
        p = self.pit("东-1")
        start, end = seven_day_window()
        self._event(p, start)  # 窗口左边界含
        self._event(p, end - timedelta(seconds=1))  # 右边界前含
        self._event(p, start - timedelta(days=1))  # 窗口外
        self._event(p, end)  # 右边界整点不含
        self._event(p, timezone.now() - timedelta(days=3))  # 三天前，不是只算当天
        data = self.seven_day()
        self.assertEqual(data["windowStart"], start.isoformat())
        self.assertEqual(data["windowEnd"], end.isoformat())
        self.assertEqual(data["count"], 3)
        self.assertEqual(sum(d["count"] for d in data["daily"]), 3)
        self.assertEqual(len(data["daily"]), 7)

    def test_count_ignores_current_drained_pits(self):
        # 当前已是已放液、但没有成功放液事件的坑，不得凑数
        self.pit("幽灵坑", status=Pit.STATUS_DRAINED)
        self.assertEqual(self.seven_day()["count"], 0)

        # 坑已经被拨回非放液态，七日台仍记它窗口内的成功放液历史
        p = self.pit("东-1")
        self.client.post(f"/pits/{p.id}/status", json={"status": "drained"})
        self.client.post(f"/pits/{p.id}/status", json={"status": "tanning"})
        p.refresh_from_db()
        self.assertEqual(p.status, Pit.STATUS_TANNING)
        self.assertEqual(
            self.seven_day()["count"],
            DrainEvent.objects.count(),
        )
        self.assertEqual(self.seven_day()["count"], 1)

    def test_events_outside_window_not_counted(self):
        p = self.pit("东-1")
        self._event(p, timezone.now() - timedelta(days=10))
        self.assertEqual(self.seven_day()["count"], 0)

    def test_board_is_read_only(self):
        resp = self.client.get("/drains/seven-day")
        self.assertEqual(resp.status_code, 200)
        for method in ("post", "put", "patch", "delete"):
            resp = getattr(self.client, method)("/drains/seven-day", json={})
            self.assertEqual(resp.status_code, 405, f"{method} 应当不允许")


class ConcurrentDrainTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username="worker1", role="worker")
        self.user.set_password("123456")
        self.user.save()
        yard = Yard.objects.create(name="南冈鞣场", village="青皮村")
        self.pit = Pit.objects.create(
            yard=yard, code="东-1", status=Pit.STATUS_TANNING, row=0, col=0
        )
        LiquorSample.objects.create(pit=self.pit, ph=4.2, operator="worker1")
        self.token = make_token(self.user.username)

    def test_two_workers_draining_same_pit_only_one_lands(self):
        barrier = threading.Barrier(2)
        outcomes = {}

        def worker(name):
            barrier.wait()
            try:
                client = TestClient(api, headers={"Authorization": f"Bearer {self.token}"})
                resp = client.post(f"/pits/{self.pit.id}/status", json={"status": "drained"})
                outcomes[name] = resp.status_code
            except Exception as exc:  # noqa: BLE001 - 把线程内异常带回主线程断言
                outcomes[name] = f"ERROR: {exc!r}"
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(n,)) for n in ("甲", "乙")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(sorted(outcomes.values(), key=str), [200, 409], repr(outcomes))
        self.pit.refresh_from_db()
        self.assertEqual(self.pit.status, Pit.STATUS_DRAINED)
        self.assertEqual(DrainEvent.objects.filter(pit=self.pit).count(), 1)
