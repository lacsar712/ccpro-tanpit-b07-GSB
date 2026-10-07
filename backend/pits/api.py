from datetime import datetime, time, timedelta

from django.db import transaction
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from pits.auth import BearerAuth, make_token
from pits.models import DrainEvent, Pit, User, Yard
from pits.rules import RuleError, assert_can_set_status, latest_ph

api = NinjaAPI(title="TanPit", urls_namespace="tanpit")
auth = BearerAuth()

SEVEN_DAYS = 7


class LoginIn(Schema):
    username: str
    password: str


class SampleIn(Schema):
    ph: float


class StatusIn(Schema):
    status: str


def pit_json(pit: Pit) -> dict:
    return {
        "id": pit.id,
        "code": pit.code,
        "status": pit.status,
        "row": pit.row,
        "col": pit.col,
        "latestPh": latest_ph(pit),
        "sampleCount": pit.samples.count(),
    }


@api.post("/auth/login")
def login(request, payload: LoginIn):
    user = User.objects.filter(username=payload.username).first()
    if user is None or not user.check_password(payload.password):
        raise HttpError(401, "用户名或密码错误")
    return {"access_token": make_token(user.username), "user": {"username": user.username, "role": user.role}}


@api.get("/auth/me", auth=auth)
def me(request):
    user = request.auth
    return {"username": user.username, "role": user.role}


@api.get("/health")
def health(request):
    return {"status": "ok", "service": "TanPit"}


@api.get("/board", auth=auth)
def board(request):
    yard = Yard.objects.prefetch_related("pits__samples").first()
    if yard is None:
        raise HttpError(404, "尚无鞣场")
    pits = sorted(yard.pits.all(), key=lambda p: (p.row, p.col))
    return {"yard": yard.name, "village": yard.village, "pits": [pit_json(p) for p in pits]}


@api.post("/pits/{pit_id}/samples", auth=auth)
def add_sample(request, pit_id: int, payload: SampleIn):
    pit = Pit.objects.filter(id=pit_id).first()
    if pit is None:
        raise HttpError(404, "坑不存在")
    pit.samples.create(ph=payload.ph, operator=request.auth.username)
    pit.refresh_from_db()
    return pit_json(pit)


@api.post("/pits/{pit_id}/status", auth=auth)
def set_status(request, pit_id: int, payload: StatusIn):
    # 规则校验在事务外读最新已提交数据，避免读快照跨过并发窗口
    pit = Pit.objects.filter(id=pit_id).first()
    if pit is None:
        raise HttpError(404, "坑不存在")
    old_status = pit.status
    try:
        assert_can_set_status(pit, payload.status)
    except RuleError as exc:
        raise HttpError(400, str(exc))
    if old_status == payload.status:
        # 重复拨同一状态按幂等处理；已放液→已放液不再记一次放液
        return pit_json(pit)
    with transaction.atomic():
        # 条件更新兜底并发：本事务第一条写语句即 UPDATE，按提交后的最新值判定。
        # 两人抢同一口鞣制中坑时，先提交者把状态改为已放液并落一笔事件；
        # 后者 WHERE status=鞣制中 失配、0 行更新 → 409，绝不产生第二笔。
        updated = Pit.objects.filter(id=pit_id, status=old_status).update(status=payload.status)
        if updated == 0:
            raise HttpError(409, "坑位状态刚被他人变更，请刷新后重试")
        if payload.status == Pit.STATUS_DRAINED:
            DrainEvent.objects.create(
                pit=pit,
                drained_at=timezone.now(),
                operator=request.auth.username,
            )
    pit.status = payload.status
    return pit_json(pit)


def seven_day_window(today=None) -> tuple[datetime, datetime]:
    """服务器日历（Asia/Shanghai）下：今天往前含今天共 7 个自然日的半开区间 [起, 止)。"""
    if today is None:
        today = timezone.localtime().date()
    start_local = datetime.combine(today - timedelta(days=SEVEN_DAYS - 1), time.min)
    start = timezone.make_aware(start_local)
    return start, start + timedelta(days=SEVEN_DAYS)


@api.get("/drains/seven-day", auth=auth)
def seven_day_drains(request):
    """七日放液台：只读。只加算窗口内真实成功拨到「已放液」的事件笔数，
    不看场地图上当前有多少口已放液坑。"""
    start, end = seven_day_window()
    events = (
        DrainEvent.objects.filter(drained_at__gte=start, drained_at__lt=end)
        .select_related("pit")
        .order_by("drained_at", "id")
    )
    daily = {start.date() + timedelta(days=i): 0 for i in range(SEVEN_DAYS)}
    items = []
    for ev in events:
        local_day = timezone.localtime(ev.drained_at).date()
        if local_day in daily:
            daily[local_day] += 1
        items.append(
            {
                "id": ev.id,
                "pit": ev.pit.code,
                "drainedAt": ev.drained_at.isoformat(),
                "operator": ev.operator,
            }
        )
    return {
        "timezone": timezone.get_current_timezone_name(),
        "windowStart": start.isoformat(),
        "windowEnd": end.isoformat(),
        "count": len(items),
        "daily": [{"date": day.isoformat(), "count": cnt} for day, cnt in sorted(daily.items())],
        "events": items,
    }
