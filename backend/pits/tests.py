import json
import threading
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import connections
from django.test import Client, TransactionTestCase
from django.utils import timezone

from pits.auth import make_token
from pits.models import DrainEvent, LiquorSample, Pit, User, Yard
from pits.seed import seed_demo

SH_TZ = ZoneInfo("Asia/Shanghai")


def drain(client: Client, pit_id: int, token: str):
    return client.post(
        f"/api/pits/{pit_id}/status",
        data=json.dumps({"status": Pit.STATUS_DRAINED}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def set_status(client: Client, pit_id: int, status: str, token: str):
    return client.post(
        f"/api/pits/{pit_id}/status",
        data=json.dumps({"status": status}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def seven_day(client: Client, token: str) -> dict:
    res = client.get("/api/drains/seven-day", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert res.status_code == 200, res.content
    return res.json()


class DrainLedgerTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username="worker", role="worker")
        self.user.set_password("123456")
        self.user.save()
        self.token = make_token("worker")
        self.yard = Yard.objects.create(name="南冈鞣场", village="青皮村")

    def make_pit(self, code: str, status: str = Pit.STATUS_TANNING, ph: float | None = 4.2) -> Pit:
        pit = Pit.objects.create(yard=self.yard, code=code, status=status, row=0, col=0)
        if ph is not None:
            LiquorSample.objects.create(pit=pit, ph=ph, operator="worker")
        return pit

    def test_successful_drain_records_one_event(self):
        client = Client()
        pit = self.make_pit("东-1")
        res = drain(client, pit.id, self.token)
        self.assertEqual(res.status_code, 200, res.content)
        pit.refresh_from_db()
        self.assertEqual(pit.status, Pit.STATUS_DRAINED)
        events = DrainEvent.objects.filter(pit=pit)
        self.assertEqual(events.count(), 1)
        event = events.get()
        self.assertEqual(event.from_status, Pit.STATUS_TANNING)
        self.assertEqual(event.operator, "worker")
        self.assertEqual(event.pit_code, "东-1")
        self.assertEqual(seven_day(client, self.token)["total"], 1)

    def test_gate_failure_writes_no_event(self):
        client = Client()
        pit = self.make_pit("中-2", ph=6.1)
        res = drain(client, pit.id, self.token)
        self.assertEqual(res.status_code, 400)
        pit.refresh_from_db()
        self.assertEqual(pit.status, Pit.STATUS_TANNING)
        self.assertEqual(DrainEvent.objects.count(), 0)

        pit_no_sample = self.make_pit("东-2", ph=None)
        res = drain(client, pit_no_sample.id, self.token)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(DrainEvent.objects.count(), 0)

    def test_sequential_duplicate_drain_is_idempotent(self):
        client = Client()
        pit = self.make_pit("东-1")
        first = drain(client, pit.id, self.token)
        second = drain(client, pit.id, self.token)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(DrainEvent.objects.filter(pit=pit).count(), 1)
        self.assertEqual(seven_day(client, self.token)["total"], 1)

    def test_redrain_cycle_counts_each_success(self):
        client = Client()
        pit = self.make_pit("东-1")
        self.assertEqual(drain(client, pit.id, self.token).status_code, 200)
        self.assertEqual(set_status(client, pit.id, Pit.STATUS_TANNING, self.token).status_code, 200)
        self.assertEqual(drain(client, pit.id, self.token).status_code, 200)
        self.assertEqual(DrainEvent.objects.filter(pit=pit).count(), 2)
        self.assertEqual(seven_day(client, self.token)["total"], 2)

    def test_count_is_event_history_not_current_drained_pits(self):
        client = Client()
        pit = self.make_pit("东-1")
        drain(client, pit.id, self.token)
        self.assertEqual(seven_day(client, self.token)["total"], 1)
        # 坑拨回鞣制中后，已成功的放液次数不回落；当前 drained 坑数已为 0。
        set_status(client, pit.id, Pit.STATUS_TANNING, self.token)
        self.assertEqual(Pit.objects.filter(status=Pit.STATUS_DRAINED).count(), 0)
        self.assertEqual(seven_day(client, self.token)["total"], 1)

    def test_seven_day_window_boundaries(self):
        client = Client()
        # 分别造三次成功放液，再把事件时间改到窗口内外的边界上。
        pit_today = self.make_pit("坑-今")
        pit_start = self.make_pit("坑-始")
        pit_before = self.make_pit("坑-外")
        drain(client, pit_today.id, self.token)
        drain(client, pit_start.id, self.token)
        drain(client, pit_before.id, self.token)

        now_local = timezone.localtime(timezone.now(), SH_TZ)
        today = now_local.date()
        start = today - timedelta(days=6)
        start_dt = datetime.combine(start, time.min, tzinfo=SH_TZ)

        DrainEvent.objects.filter(pit=pit_start).update(drained_at=start_dt)
        DrainEvent.objects.filter(pit=pit_before).update(drained_at=start_dt - timedelta(seconds=1))

        data = seven_day(client, self.token)
        self.assertEqual(data["start"], start.isoformat())
        self.assertEqual(data["end"], today.isoformat())
        self.assertEqual(len(data["days"]), 7)
        self.assertEqual(data["total"], 2)
        by_date = {d["date"]: d["count"] for d in data["days"]}
        self.assertEqual(by_date[start.isoformat()], 1)
        self.assertEqual(by_date[today.isoformat()], 1)
        # 中间日期必须补零，且桶严格按时间顺序
        self.assertEqual([d["date"] for d in data["days"]], [(start + timedelta(days=i)).isoformat() for i in range(7)])
        self.assertEqual(sum(by_date.values()), 2)

    def test_seven_day_requires_auth(self):
        res = Client().get("/api/drains/seven-day")
        self.assertEqual(res.status_code, 401)

    def test_seed_pre_drained_pits_count_as_zero(self):
        Yard.objects.all().delete()
        DrainEvent.objects.all().delete()
        seed_demo()
        self.assertGreater(Pit.objects.filter(status=Pit.STATUS_DRAINED).count(), 0)
        self.assertEqual(DrainEvent.objects.count(), 0)

    def test_concurrent_drains_record_exactly_one_event(self):
        for round_no in range(5):
            pit = self.make_pit(f"并发-{round_no}")
            barrier = threading.Barrier(2)
            results = []

            def worker():
                thread_client = Client()
                try:
                    barrier.wait()
                    results.append(drain(thread_client, pit.id, self.token).status_code)
                finally:
                    # 连接是线程局部的，线程收尾必须自行关闭。
                    connections.close_all()

            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
                self.assertFalse(t.is_alive(), "并发放液线程超时")

            self.assertEqual(sorted(results), [200, 200])
            pit.refresh_from_db()
            self.assertEqual(pit.status, Pit.STATUS_DRAINED)
            self.assertEqual(DrainEvent.objects.filter(pit=pit).count(), 1)

        client = Client()
        self.assertEqual(seven_day(client, self.token)["total"], 5)
