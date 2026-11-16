"""Data update coordinator for Bosch EasyAir."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EasyAirApi, EasyAirAuthError, EasyAirError
from .const import DOMAIN, UPDATE_INTERVAL
from .statistics import import_energy_history

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1


def us_week(day: date) -> tuple[int, int]:
    """Return (year, week) as the EasyAir app buckets it.

    The app uses moment.js en-US weeks (Sunday start, week 1 contains Jan 1), but
    files each week under the calendar year of the day itself. So Dec 29 2025 is
    (2025, 1) and Jan 1 2026 is (2026, 1).
    """
    jan1_next = date(day.year + 1, 1, 1)
    start_next = jan1_next - timedelta(days=(jan1_next.weekday() + 1) % 7)
    if day >= start_next:
        return day.year, 1
    jan1 = date(day.year, 1, 1)
    start = jan1 - timedelta(days=(jan1.weekday() + 1) % 7)
    return day.year, (day - start).days // 7 + 1


@dataclass
class UnitData:
    """Processed energy data for one gateway."""

    device: dict[str, Any]
    total: float  # lifetime kWh tracked by this integration (monotonic)
    this_week: int | None = None
    this_month: int | None = None
    last_month: int | None = None
    this_year: int | None = None
    communicating_flag: str | None = None
    monthly: dict[str, int] = field(default_factory=dict)  # "YYYY-MM" -> kWh


class EasyAirCoordinator(DataUpdateCoordinator[dict[str, UnitData]]):
    """Polls device list and energy usage."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: EasyAirApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.api = api
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._state: dict[str, dict] | None = None

    async def _async_update_data(self) -> dict[str, UnitData]:
        if self._state is None:
            self._state = await self._store.async_load() or {}
        try:
            devices = await self.api.device_list()
            raw = {d["gatewayId"]: (d, await self.api.energy_usage(d["gatewayId"])) for d in devices}
        except EasyAirAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EasyAirError as err:
            raise UpdateFailed(str(err)) from err

        now = dt_util.now()
        result: dict[str, UnitData] = {}
        for gw, (device, energy) in raw.items():
            years = {int(y["year"]): y for y in energy.get("data") or [] if "year" in y}
            monthly: dict[str, int] = {}
            for year, yd in years.items():
                for m, v in (yd.get("months") or {}).items():
                    monthly[f"{year}-{int(m) + 1:02d}"] = int(v)

            # Lifetime counter: add positive per-month deltas so the total never
            # drops when old years age out of the API response.
            st = self._state.setdefault(gw, {"total": 0.0, "months": {}})
            seen: dict[str, int] = st["months"]
            for key, value in monthly.items():
                delta = value - seen.get(key, 0)
                if delta > 0:  # ignore downward corrections; never double count
                    st["total"] += delta
                    seen[key] = value

            cur = years.get(now.year, {})
            wy, wk = us_week(now.date())
            week_data = years.get(wy, {}).get("weekly") or {}
            prev_month = (now.replace(day=1) - timedelta(days=1))
            result[gw] = UnitData(
                device=device,
                total=st["total"],
                this_week=_int(week_data.get(str(wk))),
                this_month=monthly.get(f"{now.year}-{now.month:02d}"),
                last_month=monthly.get(f"{prev_month.year}-{prev_month.month:02d}"),
                this_year=sum(int(v) for v in (cur.get("months") or {}).values()) if cur else None,
                communicating_flag=energy.get("communicatingFlag"),
                monthly=monthly,
            )
            try:
                import_energy_history(self.hass, gw, device, energy)
            except Exception:  # never let a statistics problem break polling
                _LOGGER.exception("Failed to import energy history for %s", gw)
        await self._store.async_save(self._state)
        return result


def _int(v: Any) -> int | None:
    return None if v is None else int(v)
