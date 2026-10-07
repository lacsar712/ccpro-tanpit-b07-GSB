from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from pits.auth import BearerAuth, make_token
from pits.models import DrainEvent, Pit, User, Yard
from pits.rules import RuleError, assert_can_set_status, latest_ph

api = NinjaAPI(title="TanPit", urls_namespace="tanpit")
auth = BearerAuth()

# 服务器日历：七日窗口一律按 Asia/Shanghai 的自然日切桶
SH_TZ = ZoneInfo("Asia/Shanghai")
ALLOWED_STATUS = {Pit.STATUS_FILL, Pit.STATUS_TANNING, Pit.STATUS_DRAINED}


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
    if payload.status not in ALLOWED_STATUS:
        raise HttpError(400, f"无效状态：{payload.status}")
    with transaction.atomic():
        # 先锁后读：并发放液在此串行，落败方随后读到已落库的 drained。
        pit = Pit.objects.select_for_update().filter(id=pit_id).first()
        if pit is None:
            raise HttpError(404, "坑不存在")
        old_status = pit.status
        if old_status == payload.status:
            # 幂等：双击、重试或并发落败方重复提交，不再落一笔放液记录。
            return pit_json(pit)
        try:
            assert_can_set_status(pit, payload.status)
        except RuleError as exc:
            raise HttpError(400, str(exc))
        pit.status = payload.status
        pit.save(update_fields=["status"])
        if payload.status == Pit.STATUS_DRAINED:
            # 只有成功拨入已放液才入账；只数次数，不看当前坑态。
            DrainEvent.objects.create(
                pit=pit,
                pit_code=pit.code,
                from_status=old_status,
                operator=request.auth.username,
            )
    return pit_json(pit)


@api.get("/drains/seven-day", auth=auth)
def drains_seven_day(request):
    # 服务器日历往回七天：今天 + 往前 6 个自然日，按上海零点切半开区间。
    today = timezone.localtime(timezone.now(), SH_TZ).date()
    start = today - timedelta(days=6)
    start_dt = datetime.combine(start, time.min, tzinfo=SH_TZ)
    end_dt = start_dt + timedelta(days=7)

    rows = (
        DrainEvent.objects.filter(drained_at__gte=start_dt, drained_at__lt=end_dt)
        .annotate(day=TruncDate("drained_at", tzinfo=SH_TZ))
        .values("day")
        .annotate(n=Count("id"))
    )
    counts = {row["day"]: row["n"] for row in rows}
    days = [
        {"date": (start + timedelta(days=i)).isoformat(), "count": counts.get(start + timedelta(days=i), 0)}
        for i in range(7)
    ]
    return {
        "today": today.isoformat(),
        "start": start.isoformat(),
        "end": today.isoformat(),
        "days": days,
        "total": sum(day["count"] for day in days),
    }
