# Bosch IDS outdoor unit: BLE live-data protocol

Reverse engineered from the Bosch EasyAir Android app (`com.idsmobileapp` 4.2.0,
Hermes bytecode). This is what the app's contractor **On-site Data / Live Data** screen
uses. **Status: derived from the app code, not yet verified against a real unit.**

## Enabling Bluetooth on the unit

From the app's instructions:

1. Open the access panel on the outdoor unit.
2. Hold the **Connect** button on the gateway for 4 seconds.
3. The blue Bluetooth LED starts blinking.
4. Connect, and enter the **Bluetooth PIN** when the phone/OS prompts for pairing.

The device advertises as `BOSCH_HP_XXXXXX` (or `HP_XXXXXX` on unbranded units). The
PIN is 6 digits (`^[0-9]{6}$`).

Open question: does the unit advertise/stay connectable only while the blue LED is
blinking (i.e. the Connect-button window), or all the time? Repeated 60 s scans from
indoors — detecting by the `f76aa910…` service UUID as well as the name, so an unnamed
advertisement would still match — never saw the unit while the button had **not** been
pressed, though the host may simply have been out of range of the outdoor unit. This is
the main thing to settle on real hardware: scan from a few metres away, first without
touching the unit, then within the LED-blink window.

The PIN (`bluetoothPassword`) is **only** used for OS-level pairing — the app displays it
for the user to type into the system pairing dialog and never writes it over GATT. So if
the GATT characteristics turn out not to require encryption, no PIN is needed; the probe
now tries the unpaired flow first and reports if an auth error demands pairing.

## GATT

| | UUID |
| --- | --- |
| Service | `f76aa910-6535-4020-9b1f-395ab4e9a676` |
| Notify ("readCharacteristic") | `f76aa911-6535-4020-9b1f-395ab4e9a676` |
| Write ("randomNumberCharacteristic") | `f76aa911-6535-4020-9b1f-395ab4e9a678` |

## Session

1. Connect, then `discoverAllServicesAndCharacteristics`.
2. Pair with the 6-digit PIN as a standard BLE passkey (the app relies on the OS
   pairing dialog; a wrong PIN shows "incorrect PIN").
3. Subscribe to notifications on the notify characteristic.
4. Write 3 random bytes, with response, to the write characteristic. The app writes
   `getRandomString(4)` (4 alphanumeric chars), and react-native-ble-plx treats that as
   base64, which decodes to 3 bytes. Nothing in it depends on the PIN; it looks like a
   "start streaming" trigger.
5. Notifications arrive. The app keeps merging them into one register map and treats
   the data as complete after more than 96 registers (older units) or 103 (newer).

## Packet format

Each notification is about 21 bytes. **Byte 0 is the packet number**, which selects a
row from the mapping table (`tools/easyair_ble/tables.json`). Each register lists
1-based byte positions; the app concatenates the bytes in the listed order, so `[5, 4]`
means `value = (byte[4] << 8) | byte[3]` with 0-based indexing (low byte first on the
wire).

Two tables exist:

- `new` (`bleDataMapping`): used for model30 (`BOVx-xxMTB-M19E`) or the
  `newMappingPartNumbers` list. Packets 0 to 9.
- `v22` (`bleDataMapping22`): everything else. Packets 0 to 8.

Packet 9 only exists in `new`, which allows auto-detection.

### Value decoding

- **Default:** a 16-bit value with bit 15 as the sign (`v - 65536` if `v & 0x8000`).
- **30004, 30005, 30007, 30013** (temperatures): `hi == 1 ? -lo : lo` (sign byte +
  magnitude, °F).
- **30036, 30037, 30039–30047** (fault codes): each byte is a 7-segment pattern
  (`192→0, 249→1, 164→2, 176→3, 153→4, 146→5, 130→6, 248→7, 128→8, 144→9, 136→A,
  131→B, 198→C, 161→D, 134→E, 142→F, 191→-, 140→P, 193→U, 135→T, 199→L, 137→H, 143→r,
  241→J, 171→n, 255→blank`).
- **30024** compressor current: `value / 2` A.
- **30029** continuous compressor run time: `(hi*256+lo) / 60` (displayed as minutes).
- **30032** control board version: `hi*10 + lo`.
- **Divided by 10 when displayed:** 30064, 30065, 30070, 30071, 30072, 30082, 30120,
  30123, 30124, 30125, 30127, 30128, 30133, 30134, 40005, 40007.
- **10xxx** registers are single-byte flags (DIP switches, Y/B/W calls, defrost, and
  similar).

### Registers of interest

| Reg | Name | Unit |
| --- | --- | --- |
| 30056 | Outdoor unit power | W |
| 30054 | Indoor blower power | W |
| 30124 | Outdoor unit input current | A (÷10) |
| 30030 | Input (AC) voltage | V |
| 30024 | Compressor current | A (÷2) |
| 30003 | Compressor speed | Hz |
| 30002 | Unit mode | |
| 30005 | T4 outdoor ambient | °F |
| 30004 | T3 outdoor coil | °F |
| 30006 / 30007 | Discharge / suction temp | °F |
| 30010 / 30011 | Evaporating / condensing pressure | psig |
| 30070 / 30071 | T1 indoor ambient / T2 indoor coil | °F (÷10) |
| 30036 / 30037 | Active / last fault code | 7-seg |
| 10010 | Defrost mode | flag |
| 10011 / 10012 / 10013 | Y / B / W thermostat calls | flag |

## Tools

```sh
cd tools
pip install bleak
python3 -m easyair_ble.probe       # scan, connect, pair, dump + decode, save raw packets
```
