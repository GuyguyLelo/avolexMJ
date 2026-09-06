"""Agrégats du tableau de bord cabinet."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from apps.billing.models import Invoice, InvoiceStatus, TimeEntry
from apps.calendar_app.models import Event, EventType, HearingStatus
from apps.matters.models import Matter, MatterScale, MatterStatus
from apps.procurations.models import Procuration, ProcurationStatus
from apps.tenants.models import Cabinet, Membership
from apps.tenants.services import is_platform_admin

ACTIVE_MATTER_STATUSES = (
    MatterStatus.OPEN,
    MatterStatus.IN_PROGRESS,
    MatterStatus.ON_HOLD,
)

UNPAID_STATUSES = (InvoiceStatus.SENT, InvoiceStatus.OVERDUE)


def _matters_qs(*, cabinet: Cabinet, user: Any | None = None):
    qs = Matter.objects.filter(cabinet=cabinet)
    if user is not None and not is_platform_admin(user):
        from apps.procurations.services import authorized_matter_ids_for_cabinet

        qs = qs.filter(pk__in=authorized_matter_ids_for_cabinet(cabinet=cabinet))
    return qs


@dataclass(frozen=True)
class DashboardStats:
    """KPIs simples du cabinet."""

    matters_active: int
    matters_total: int
    events_upcoming: int
    hearings_upcoming: int
    unbilled_hours_amount: Decimal
    unpaid_invoices: int
    revenue_month: Decimal
    procurations_valid: int


def build_dashboard_stats(*, cabinet: Cabinet, user: Any | None = None) -> DashboardStats:
    """Calcule les indicateurs du dashboard pour un cabinet."""
    today = timezone.localdate()
    month_start = today.replace(day=1)
    now = timezone.now()
    matters = _matters_qs(cabinet=cabinet, user=user)

    matters_total = matters.filter(is_archived=False).count()
    matters_active = matters.filter(
        is_archived=False,
        status__in=ACTIVE_MATTER_STATUSES,
    ).count()
    events_upcoming = Event.objects.filter(
        cabinet=cabinet,
        starts_at__gte=now,
        is_done=False,
    ).count()
    hearings_upcoming = Event.objects.filter(
        cabinet=cabinet,
        event_type=EventType.HEARING,
        starts_at__gte=now,
        hearing_status__in=(HearingStatus.SCHEDULED, ""),
    ).count()

    unbilled_amount = Decimal("0.00")
    for entry in TimeEntry.objects.filter(
        cabinet=cabinet,
        is_billable=True,
        invoice__isnull=True,
        ended_at__isnull=False,
    ).only("duration_minutes", "hourly_rate")[:500]:
        unbilled_amount += entry.amount

    unpaid_invoices = Invoice.objects.filter(
        cabinet=cabinet,
        status__in=UNPAID_STATUSES,
    ).count()

    revenue = Invoice.objects.filter(
        cabinet=cabinet,
        status=InvoiceStatus.PAID,
        paid_at__gte=month_start,
    ).aggregate(total=Coalesce(Sum("total"), Decimal("0.00")))

    procurations_valid = (
        Procuration.objects.filter(
            cabinet=cabinet,
            status=ProcurationStatus.GRANTED,
        )
        .filter(
            Q(expires_at__isnull=True) | Q(expires_at__gte=today),
            Q(valid_from__isnull=True) | Q(valid_from__lte=today),
        )
        .count()
    )

    return DashboardStats(
        matters_active=matters_active,
        matters_total=matters_total,
        events_upcoming=events_upcoming,
        hearings_upcoming=hearings_upcoming,
        unbilled_hours_amount=unbilled_amount.quantize(Decimal("0.01")),
        unpaid_invoices=unpaid_invoices,
        revenue_month=Decimal(revenue["total"] or 0).quantize(Decimal("0.01")),
        procurations_valid=procurations_valid,
    )


def recent_matters(*, cabinet: Cabinet, user: Any | None = None, limit: int = 5) -> list[Matter]:
    """Derniers dossiers mis à jour (procuration valide pour le cabinet)."""
    return list(
        _matters_qs(cabinet=cabinet, user=user)
        .filter(is_archived=False)
        .select_related("responsible_lawyer")
        .order_by("-updated_at")[:limit]
    )


def upcoming_hearings(*, cabinet: Cabinet, limit: int = 5) -> list[Event]:
    """Prochaines audiences planifiées."""
    return list(
        Event.objects.filter(
            cabinet=cabinet,
            event_type=EventType.HEARING,
            starts_at__gte=timezone.now(),
            hearing_status__in=(HearingStatus.SCHEDULED, ""),
        )
        .select_related("matter")
        .order_by("starts_at")[:limit]
    )


def upcoming_events(*, cabinet: Cabinet, limit: int = 5) -> list[Event]:
    """Prochains événements."""
    return list(
        Event.objects.filter(cabinet=cabinet, starts_at__gte=timezone.now())
        .select_related("matter")
        .order_by("starts_at")[:limit]
    )


@dataclass(frozen=True)
class CabinetOverview:
    """Résumé d'activité d'un cabinet (supervision plateforme)."""

    cabinet: Cabinet
    members_count: int
    matters_active: int
    hearings_upcoming: int
    unpaid_invoices: int


@dataclass(frozen=True)
class PlatformStats:
    """Totaux globaux plateforme."""

    cabinets_count: int
    members_count: int
    matters_active: int
    hearings_upcoming: int
    unpaid_invoices: int
    procurations_granted: int


def build_platform_stats() -> PlatformStats:
    """Agrégats cross-cabinet pour l'administrateur plateforme."""
    now = timezone.now()
    cabinets_count = Cabinet.objects.filter(is_active=True).count()
    members_count = Membership.objects.filter(is_active=True).count()
    matters_active = Matter.unscoped.filter(
        is_archived=False,
        status__in=ACTIVE_MATTER_STATUSES,
    ).count()
    hearings_upcoming = Event.unscoped.filter(
        event_type=EventType.HEARING,
        starts_at__gte=now,
        hearing_status__in=(HearingStatus.SCHEDULED, ""),
    ).count()
    unpaid_invoices = Invoice.unscoped.filter(status__in=UNPAID_STATUSES).count()
    procurations_granted = Procuration.unscoped.filter(status=ProcurationStatus.GRANTED).count()
    return PlatformStats(
        cabinets_count=cabinets_count,
        members_count=members_count,
        matters_active=matters_active,
        hearings_upcoming=hearings_upcoming,
        unpaid_invoices=unpaid_invoices,
        procurations_granted=procurations_granted,
    )


def get_cabinet_overview(cabinet: Cabinet) -> CabinetOverview:
    """Indicateurs d'activité pour un cabinet (y compris inactif)."""
    now = timezone.now()
    return CabinetOverview(
        cabinet=cabinet,
        members_count=Membership.objects.filter(cabinet=cabinet, is_active=True).count(),
        matters_active=Matter.unscoped.filter(
            cabinet=cabinet,
            is_archived=False,
            status__in=ACTIVE_MATTER_STATUSES,
        ).count(),
        hearings_upcoming=Event.unscoped.filter(
            cabinet=cabinet,
            event_type=EventType.HEARING,
            starts_at__gte=now,
            hearing_status__in=(HearingStatus.SCHEDULED, ""),
        ).count(),
        unpaid_invoices=Invoice.unscoped.filter(
            cabinet=cabinet,
            status__in=UNPAID_STATUSES,
        ).count(),
    )


def list_cabinet_overviews(*, limit: int = 50) -> list[CabinetOverview]:
    """Liste les cabinets avec indicateurs d'activité."""
    cabinets = list(Cabinet.objects.filter(is_active=True).order_by("name")[:limit])
    return [get_cabinet_overview(cabinet) for cabinet in cabinets]


def recent_platform_activity(*, limit: int = 10) -> list[Matter]:
    """Derniers dossiers mis à jour, tous cabinets confondus."""
    return list(
        Matter.unscoped.filter(is_archived=False)
        .select_related("cabinet", "responsible_lawyer")
        .order_by("-updated_at")[:limit]
    )


def upcoming_platform_hearings(*, limit: int = 10) -> list[Event]:
    """Prochaines audiences, tous cabinets confondus."""
    return list(
        Event.unscoped.filter(
            event_type=EventType.HEARING,
            starts_at__gte=timezone.now(),
            hearing_status__in=(HearingStatus.SCHEDULED, ""),
        )
        .select_related("cabinet", "matter")
        .order_by("starts_at")[:limit]
    )


_MONTH_LABELS_FR = (
    "",
    "janv.",
    "févr.",
    "mars",
    "avr.",
    "mai",
    "juin",
    "juil.",
    "août",
    "sept.",
    "oct.",
    "nov.",
    "déc.",
)


def _month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def _shift_month(value: date, delta: int) -> date:
    month_index = value.month - 1 + delta
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _as_month(value: object) -> date | None:
    if isinstance(value, datetime):
        return date(value.year, value.month, 1)
    if isinstance(value, date):
        return date(value.year, value.month, 1)
    return None


def _month_label(value: date) -> str:
    return f"{_MONTH_LABELS_FR[value.month]} {value.year}"


def _counts_by_month(rows: list[dict[str, Any]], *, key: str = "total") -> dict[date, int]:
    out: dict[date, int] = {}
    for row in rows:
        month = _as_month(row.get("month"))
        if month is None:
            continue
        out[month] = int(row.get(key) or 0)
    return out


def _amounts_by_month(rows: list[dict[str, Any]], *, key: str = "total") -> dict[date, float]:
    out: dict[date, float] = {}
    for row in rows:
        month = _as_month(row.get("month"))
        if month is None:
            continue
        out[month] = float(row.get(key) or 0)
    return out


def _month_window(*, months: int) -> tuple[date, list[date]]:
    today = timezone.localdate()
    first_month = _shift_month(_month_start(today.year, today.month), 1 - months)
    return first_month, [_shift_month(first_month, i) for i in range(months)]


def build_platform_charts(*, cabinet_limit: int = 8) -> dict[str, Any]:
    """Séries pour les graphiques de supervision."""
    matters_by_cabinet = [
        {"label": row["cabinet__name"] or "—", "value": int(row["total"])}
        for row in (
            Matter.unscoped.filter(is_archived=False, status__in=ACTIVE_MATTER_STATUSES)
            .values("cabinet__name")
            .annotate(total=Count("id"))
            .order_by("-total")[:cabinet_limit]
        )
    ]

    procurations_by_status = [
        {
            "key": row["status"],
            "label": str(ProcurationStatus(row["status"]).label),
            "value": int(row["total"]),
        }
        for row in (
            Procuration.unscoped.values("status").annotate(total=Count("id")).order_by("-total")
        )
        if row["status"]
    ]

    matters_by_scale = [
        {
            "key": row["scale"],
            "label": str(MatterScale(row["scale"]).label),
            "value": int(row["total"]),
        }
        for row in (
            Matter.unscoped.filter(is_archived=False, status__in=ACTIVE_MATTER_STATUSES)
            .values("scale")
            .annotate(total=Count("id"))
            .order_by("-total")
        )
        if row["scale"]
    ]

    return {
        "matters_by_cabinet": matters_by_cabinet,
        "procurations_by_status": procurations_by_status,
        "matters_by_scale": matters_by_scale,
    }


def build_cabinet_charts(*, cabinet: Cabinet, months: int = 6) -> dict[str, Any]:
    """Séries pour le tableau de bord d'un cabinet."""
    first_month, month_starts = _month_window(months=months)

    matters_by_status = [
        {
            "key": status.value,
            "label": str(status.label),
            "value": int(
                Matter.objects.filter(cabinet=cabinet, is_archived=False, status=status).count()
            ),
        }
        for status in MatterStatus
    ]
    matters_by_status = [row for row in matters_by_status if row["value"]]

    matter_months = _counts_by_month(
        list(
            Matter.objects.filter(cabinet=cabinet, created_at__date__gte=first_month)
            .annotate(month=TruncMonth("created_at"))
            .values("month")
            .annotate(total=Count("id"))
        )
    )
    hearing_months = _counts_by_month(
        list(
            Event.objects.filter(
                cabinet=cabinet,
                event_type=EventType.HEARING,
                starts_at__date__gte=first_month,
            )
            .annotate(month=TruncMonth("starts_at"))
            .values("month")
            .annotate(total=Count("id"))
        )
    )
    activity_by_month = [
        {
            "label": _month_label(month),
            "matters": matter_months.get(month, 0),
            "hearings": hearing_months.get(month, 0),
        }
        for month in month_starts
    ]

    revenue_months = _amounts_by_month(
        list(
            Invoice.objects.filter(
                cabinet=cabinet,
                status=InvoiceStatus.PAID,
                paid_at__gte=first_month,
            )
            .annotate(month=TruncMonth("paid_at"))
            .values("month")
            .annotate(total=Coalesce(Sum("total"), Decimal("0")))
        )
    )
    revenue_by_month = [
        {
            "label": _month_label(month),
            "value": round(revenue_months.get(month, 0.0), 2),
        }
        for month in month_starts
    ]

    return {
        "matters_by_status": matters_by_status,
        "activity_by_month": activity_by_month,
        "revenue_by_month": revenue_by_month,
    }
