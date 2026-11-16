# Bosch EasyAir for Home Assistant

Unofficial Home Assistant integration that pulls heat pump electricity usage from the
Bosch **EasyAir** cloud (Bosch IDS heat pumps with a WiFi gateway) so you can track it
in the **Energy dashboard**, without using the phone app.

> Not affiliated with or endorsed by Bosch. It uses the same cloud API as the EasyAir app,
> which may change without notice.

## Sensors

One device is created per heat pump gateway:

| Sensor | Notes |
| --- | --- |
| **Total energy** (kWh) | `total_increasing`. **Use this one in the Energy dashboard.** |
| Energy this week (kWh) | Sunday-start week, as shown in the app |
| Energy this month (kWh) | |
| Energy last month (kWh) | |
| Energy this year (kWh) | Attribute `monthly_kwh` contains per-month history |
| Service status | Diagnostic |

The cloud reports whole kWh per week and month, and it updates periodically rather than
in real time, so usage shows up in the Energy dashboard in steps. Data is polled every
30 minutes.

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/dangerouslaser/hass-easyair`
   as an **Integration**.
2. Install **Bosch EasyAir** and restart Home Assistant.
3. Settings → Devices & services → **Add integration** → **Bosch EasyAir**.

## Signing in (SingleKey ID)

EasyAir uses SingleKey ID, which can use passkeys, so sign-in happens in your browser.
The EasyAir login only redirects back to the mobile app (`idsmobileapp://…`), so you copy
that redirect into Home Assistant by hand:

1. Open your browser's DevTools (F12) → **Network** tab and enable **Preserve log**
   (Chrome) / **Persist Logs** (Firefox).
2. In the same tab, open the login link shown in the setup dialog and sign in.
3. The browser will say it can't open the address. In the Network list, click the
   `idpresponse` request (status **302**) and copy the **Location** response header. It
   looks like `idsmobileapp://?code=…`.
4. Paste it into the dialog within 5 minutes.

The integration then refreshes its own tokens. If the session ever expires, Home
Assistant prompts you to repeat these steps (re-authentication).

## Adding to the Energy dashboard

The integration imports the cloud's weekly history (back to installation) into Home
Assistant's long-term statistics as **`<heat pump name> energy`**
(`easyair:<gateway>_energy`), and keeps it updated on every poll.

Settings → Dashboards → **Energy** → *Individual devices* (or *Electricity grid →
consumption*) → add **`<heat pump name> energy`** (the statistic, not the
**Total energy** sensor). Don't add both, or usage is counted twice.

Resolution is weekly: the cloud has no daily or hourly data, so each week's usage is
stamped on that week's Sunday. Week and month views are accurate; day and hour views
show the whole week on Sunday.

## Development

`tools/easyair` is a small standalone CLI (stdlib only) for exploring the API:

```sh
cd tools
python3 -m easyair.cli login      # prints a login URL
python3 -m easyair.cli finish 'idsmobileapp://?code=...'
python3 -m easyair.cli devices
python3 -m easyair.cli energy <gatewayId>
```

## How it works

- Auth: AWS Cognito Hosted UI at `auth.smart-climate-ids.com` (public client, PKCE),
  federated to SingleKey ID through the `IDS-TTNA` identity provider.
- API: `https://api.smart-climate-ids.com` with `Authorization: Bearer <access token>`
  - `GET /homeowner/devicelist`
  - `GET /energyusage/{gatewayId}` → `{year, months{0-11}, weekly{1-53}}` in kWh
