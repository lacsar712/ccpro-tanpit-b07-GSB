from datetime import timedelta

from django.utils import timezone

from pits.models import DrainEvent, LiquorSample, Pit, User, Yard


def seed_demo() -> None:
    admin, _ = User.objects.get_or_create(username="admin", defaults={"role": "admin"})
    admin.role = "admin"
    admin.set_password("123456")
    admin.save()
    worker, _ = User.objects.get_or_create(username="worker", defaults={"role": "worker"})
    worker.role = "worker"
    worker.set_password("123456")
    worker.save()
    if Yard.objects.exists():
        return
    yard = Yard.objects.create(name="南冈鞣场", village="青皮村")
    # (坑号, 状态, 行, 列, 酸碱, 放液发生于多少天前)；非已放液坑为 None
    # 场地图有 2 口已放液坑，但只有 1 笔落在七日内，看板数应为 1 而非 2
    layout = [
        ("东-1", Pit.STATUS_TANNING, 0, 0, 4.2, None),
        ("东-2", Pit.STATUS_FILL, 0, 1, None, None),
        ("中-1", Pit.STATUS_DRAINED, 1, 0, 4.6, 3),
        ("中-2", Pit.STATUS_TANNING, 1, 1, 6.1, None),
        ("西-1", Pit.STATUS_FILL, 2, 0, None, None),
        ("西-2", Pit.STATUS_DRAINED, 2, 1, 3.8, 9),
    ]
    now = timezone.now()
    for code, status, row, col, ph, drained_days_ago in layout:
        pit = Pit.objects.create(yard=yard, code=code, status=status, row=row, col=col)
        if ph is not None:
            LiquorSample.objects.create(pit=pit, ph=ph, operator="worker")
        if drained_days_ago is not None:
            DrainEvent.objects.create(
                pit=pit,
                drained_at=now - timedelta(days=drained_days_ago),
                operator="worker",
            )
