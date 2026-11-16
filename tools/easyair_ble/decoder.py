"""Decoder for the Bosch IDS outdoor-unit BLE live-data stream.

Re-implements `bleDataMapper` / `handleSpecialCases` from the EasyAir app
(com.idsmobileapp 4.2.0). See docs/ble-protocol.md.
"""
from __future__ import annotations

import json
from pathlib import Path

SERVICE_UUID = "f76aa910-6535-4020-9b1f-395ab4e9a676"
NOTIFY_CHAR_UUID = "f76aa911-6535-4020-9b1f-395ab4e9a676"   # "readCharacteristic"
TRIGGER_CHAR_UUID = "f76aa911-6535-4020-9b1f-395ab4e9a678"  # "randomNumberCharacteristic"
NAME_PREFIXES = ("BOSCH_HP_", "HP_")

TABLES = json.loads((Path(__file__).with_name("tables.json")).read_text())

# Sign byte + magnitude (hi == 1 -> negative)
SIGNED_MAG = {30004, 30005, 30007, 30013}
FAULT_REGS = {30036, 30037, *range(30039, 30048)}
SPECIAL = {30004, 30005, 30007, 30010, 30011, 30013, 30024, 30028, 30029, 30030,
           30031, 30032, 30036, 30037, *range(30039, 30048)}
DIVIDE_BY_10 = {30072, 30082, 30120, 30133, 30134, 40005, 40007, 30127, 30128,
                30123, 30064, 30065, 30070, 30071, 30124, 30125}

# 7-segment display byte -> character
SEVEN_SEG = {192: "0", 249: "1", 164: "2", 176: "3", 153: "4", 146: "5", 130: "6",
             248: "7", 128: "8", 144: "9", 136: "A", 131: "B", 198: "C", 161: "D",
             134: "E", 142: "F", 191: "-", 140: "P", 255: "", 193: "U", 135: "T",
             199: "L", 137: "H", 143: "r", 241: "J", 171: "n"}

NAMES = {
    30002: ("Unit mode", None), 30003: ("Compressor speed", "Hz"),
    30004: ("T3 outdoor coil temp", "°F"), 30005: ("T4 outdoor ambient temp", "°F"),
    30006: ("T5 compressor discharge temp", "°F"), 30007: ("T6 compressor suction temp", "°F"),
    30008: ("T3L outdoor coil outlet temp", "°F"), 30009: ("Tf control board temp", "°F"),
    30010: ("Pe evaporating pressure", "psig"), 30011: ("Pc condensing pressure", "psig"),
    30012: ("Tes target evaporating temp", "°F"), 30013: ("Te evaporating temp", "°F"),
    30014: ("Tcs target condensing temp", "°F"), 30015: ("Tc condensing temp", "°F"),
    30016: ("Target discharge superheat", "°F"), 30017: ("Discharge superheat", "°F"),
    30024: ("Compressor current", "A"), 30025: ("Outdoor fan stage", None),
    30027: ("Outdoor unit capacity", "ton"), 30028: ("EEV A opening", "steps"),
    30029: ("Continuous compressor run time", "min"), 30030: ("Input voltage", "V"),
    30031: ("DC bus voltage", "V"), 30032: ("Control board version", None),
    30034: ("Liquid valve subcool", "°F"), 30035: ("Suction superheat", "°F"),
    30036: ("Active fault code", None), 30037: ("Last fault code", None),
    30054: ("Indoor blower power", "W"), 30056: ("Outdoor unit power", "W"),
    30064: ("T6A injection HX inlet temp", "°F"), 30065: ("T6B injection HX outlet temp", "°F"),
    30067: ("EEV C opening", "steps"), 30070: ("T1 indoor ambient temp", "°F"),
    30071: ("T2 indoor coil temp", "°F"), 30074: ("Indoor unit software version", None),
    30082: ("T1s estimated set point", "°F"), 30117: ("Gas valve superheat", "°F"),
    30123: ("T7 outdoor outlet temp", "°F"), 30124: ("Outdoor unit input current", "A"),
    30125: ("Outdoor fan current", "A"), 30126: ("Heat kit staging", None),
    40010: ("Demand response", None),
    10011: ("Y call", None), 10012: ("B call", None), 10013: ("W call", None),
    10010: ("Defrost mode", None), 10008: ("Oil return mode", None), 10014: ("Force mode", None),
}


def _s16(v: int) -> int:
    """App's hexToDec: parseInt(hex, 16) with bit 15 treated as sign."""
    return v - 65536 if v & 0x8000 else v


def _special(reg: int, hi: int, lo: int):
    if reg in SIGNED_MAG:
        return -lo if hi == 1 else lo
    if reg in FAULT_REGS:
        a, b = SEVEN_SEG.get(hi), SEVEN_SEG.get(lo)
        if a is None or b is None:
            return (SEVEN_SEG.get(hi, "") + "0") if b == "0" else ""
        return a + b
    if reg == 30029:
        return round((hi * 256 + lo) / 60, 1)  # seconds -> minutes
    if reg == 30032:
        return hi * 10 + lo
    return hi * 256 + lo


def decode_packet(data: bytes, table: str = "v22") -> dict[int, object]:
    """Decode one notification into {register: value} (app display scaling applied)."""
    if not data:
        return {}
    mapping = TABLES[table].get(str(data[0]))
    if not mapping:
        return {}
    out: dict[int, object] = {}
    for reg_s, positions in mapping.items():
        reg = int(reg_s)
        if max(positions) > len(data):
            continue
        raw_bytes = [data[p - 1] for p in positions]  # big-endian concat as the app does
        raw = int.from_bytes(bytes(raw_bytes), "big")
        if reg == 30024:
            val = _s16(raw) / 2
        elif reg in SPECIAL and len(raw_bytes) == 2:
            val = _special(reg, raw_bytes[0], raw_bytes[1])
        else:
            val = _s16(raw)
        if reg in DIVIDE_BY_10 and isinstance(val, (int, float)):
            val = val / 10
        out[reg] = val
    return out


def guess_table(packet_types: set[int]) -> str:
    """Packet type 9 only exists in the newer mapping."""
    return "new" if 9 in packet_types else "v22"


def describe(values: dict[int, object]) -> list[str]:
    lines = []
    for reg in sorted(values):
        name, unit = NAMES.get(reg, (f"reg {reg}", None))
        lines.append(f"{reg:>5}  {name:<34} {values[reg]}{' ' + unit if unit else ''}")
    return lines
