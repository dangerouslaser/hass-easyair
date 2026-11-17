"""Backfill the Energy dashboard from Bosch EasyAir weekly history.

The cloud only exposes whole-kWh totals per ISO-ish week (and per month); there is
no daily or hourly breakdown for a homeowner account. We turn the weekly buckets
into Home Assistant long-term statistics so the Energy dashboard shows history and
keeps updating. Resolution is therefore weekly: each week's energy is spread evenly
over its days (the current week over the days elapsed so far), so week and month views
are exact and day bars show that week's daily average.

This is an *external* statistic (source = this integration), separate from the live
`energy_total` sensor. Add this one to the Energy dashboard, not the sensor, or usage
would be counted twice.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def statistic_id(gateway_id: str) -> str:
    """A valid, stable external statistic id for one gateway."""
    slug = re.sub(r"[^a-z0-9]+", "_", gateway_id.lower()).strip("_")
    return f"{DOMAIN}:{slug}_energy"


def _sunday_on_or_before_jan1(year: int) -> date:
    """Sunday that starts week 1 of `year` (the Sunday on/before Jan 1)."""
    jan1 = date(year, 1, 1)
    return jan1 - timedelta(days=(jan1.weekday() + 1) % 7)


def _week_start(year: int, week: int, lower: date, upper: date) -> date:
    """Map an app (year, week) bucket to the real Sunday it starts on.

    Weeks >= 2 are a straight offset from week 1. Week 1 is ambiguous in the app's
    own scheme (both early-January and the Dec/Jan boundary week get filed under
    key "1"), so we pick whichever candidate Sunday falls inside the device's data
    window [lower, upper]; ties prefer the normal early-January reading.
    """
    if week != 1:
        return _sunday_on_or_before_jan1(year) + timedelta(days=(week - 1) * 7)
    early = _sunday_on_or_before_jan1(year)  # early January of `year`
    boundary = _sunday_on_or_before_jan1(year + 1)  # Dec/Jan boundary week
    early_ok = lower <= early <= upper
    boundary_ok = lower <= boundary <= upper
    if boundary_ok and not early_ok:
        return boundary
    return early


def _build_points(energy: dict[str, Any], service_start_ms: int | None) -> list[StatisticData]:
    now = dt_util.now()
    upper = now.date() + timedelta(days=1)
    if service_start_ms:
        lower = dt_util.utc_from_timestamp(service_start_ms / 1000).date() - timedelta(days=7)
    else:
        lower = date(2000, 1, 1)

    # Merge by week-start so a boundary week split across two year buckets is summed.
    by_start: dict[date, float] = {}
    for yd in energy.get("data") or []:
        if "year" not in yd:
            continue
        year = int(yd["year"])
        for wk_s, val in (yd.get("weekly") or {}).items():
            try:
                wk = int(wk_s)
                v = float(val)
            except (TypeError, ValueError):
                continue
            start = _week_start(year, wk, lower, upper)
            by_start[start] = by_start.get(start, 0.0) + v

    # Spread each week evenly over its days (only the days elapsed so far for the
    # current week). Stamping a whole week on one Sunday left Monday-start week
    # views empty and piled the week onto a single day bar.
    today = now.date()
    points: list[StatisticData] = []
    running = 0.0
    for week_start, kwh in sorted(by_start.items()):
        if week_start > today:
            continue
        days = min(7, (today - week_start).days + 1)
        per_day = kwh / days
        for i in range(days):
            day = week_start + timedelta(days=i)
            running += per_day
            start = dt_util.as_utc(dt_util.start_of_local_day(day)).replace(
                minute=0, second=0, microsecond=0
            )
            # sum = cumulative including this day (HA convention); state = day kWh.
            points.append(StatisticData(start=start, state=per_day, sum=running))
    return points


def import_energy_history(
    hass: HomeAssistant, gateway_id: str, device: dict[str, Any], energy: dict[str, Any]
) -> None:
    """Push the full weekly history for one gateway into long-term statistics.

    Idempotent: recomputes and re-imports the whole series each call, so the cloud's
    occasional downward corrections and the growing current week are self-healing.
    """
    points = _build_points(energy, device.get("serviceStartDate"))
    if not points:
        return
    name = device.get("ODUName") or "Bosch heat pump"
    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        unit_class="energy",
        has_sum=True,
        name=f"{name} energy",
        source=DOMAIN,
        statistic_id=statistic_id(gateway_id),
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    )
    async_add_external_statistics(hass, metadata, points)
    _LOGGER.debug("Imported %d weekly statistics for %s", len(points), gateway_id)
