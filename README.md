# Tuya2Matter

A Home Assistant add-on that bridges Tuya smart devices into a Matter fabric. Once paired, your Tuya devices appear as native Matter devices and can be controlled by Home Assistant, Apple Home, Google Home, or any Matter-compatible controller — without any cloud dependency for day-to-day operation.

---

## How It Works

```
Tuya Cloud API ──────┐
                     ├──► TuyaDevice (per device abstraction)
Tuya LAN (TCP/UDP) ──┘         │
                                ▼
                       Tuya2Matter mapper
                                │
                                ▼
                     Matter ServerNode (bridge)
                                │
                     ┌──────────┴──────────┐
                     ▼                     ▼
              Home Assistant         Apple Home / Google Home
              Matter controller      (any Matter controller)
```

1. **Authentication** — on first run the add-on displays a Tuya QR code. Scan it with the Smart Life / Tuya Smart app to authorise access. Credentials are cached to `/data/tuya/credential.json` and auto-refreshed every 100 minutes.
2. **Device discovery** — the add-on fetches your full device list from Tuya Cloud and caches it to `/data/tuya/devices.json`. The cache is refreshed every 12 hours.
3. **Local connection** — the add-on listens on UDP ports 6666, 6667, 6699, and 7000 for Tuya broadcast packets. When a device announces itself it opens a persistent TCP connection on port 6668, negotiates the session key (protocol 3.3 / 3.4 / 3.5), and streams DPS state in real time. Disconnected devices are retried via an ARP scan every 10 minutes.
4. **Matter bridge** — each connected Tuya device is registered as a bridged endpoint inside a single Matter aggregator. State flows bidirectionally: Tuya DPS updates are pushed to Matter attributes, and Matter commands are translated back to Tuya DPS `setDps` calls.

---

## Supported Device Types

| Tuya category | Matter device type | Notes |
|---|---|---|
| `kg`, `tdq`, `cz`, `znjdq`, `pc` | OnOff Plug-in Unit (switch) | Supports up to 4 gang. Devices with `cur_current` also expose ElectricalPowerMeasurement (voltage, current, active power) |
| `clkg`, `cl` | Window Covering | Supports `percent_control` / `percent_state` for position-aware lift; falls back to open/close/stop commands |
| `hps` | Occupancy Sensor | |
| `mcs` | Contact / Binary Sensor | |
| `wxkg` | Generic Switch (button) | Single click, double click, long press |
| `dd` | Temperature-tuneable Light | |
| `fs` | Fan (MultiSpeed) | 5-speed mapping; optional on/off light sub-device |
| `jtmspro` | Door Lock | Read lock state via `closed_opened` DPS |
| `hjjcy` | Air Quality Sensor | Temperature, humidity, PM1/PM2.5/PM10, TVOC, air quality index |

### Virtual Switches

You can create Matter switch devices that are not backed by a physical Tuya device. These are useful as helper entities for automations. Set the `vitural_switches` option (comma-separated names) and the add-on will register a persistent OnOff endpoint for each name.

---

## Installation

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**.
2. Click **⋮ → Repositories** and add:
   ```
   https://github.com/duongvanba/tuya2matter
   ```
3. The **Tuya2Matter** add-on will appear in the store. Click **Install**.

---

## Configuration

| Option | Type | Description |
|---|---|---|
| `user_code` | string | Your Tuya/Smart Life user code (see below). Required. |
| `tuya2mqtt_debug` | string | Set to `all` to enable verbose TCP connection logs, or a comma-separated list of device IDs to debug specific devices. Leave blank to disable. |
| `vitural_switches` | string | Comma-separated list of virtual switch names to expose as Matter devices (e.g. `Lamp Scene,Night Mode`). |

### Finding Your User Code

1. Open the **Smart Life** or **Tuya Smart** app.
2. Tap the **Me** tab.
3. Tap the gear icon ⚙️ (top-right) → **Account and Security**.
4. Your **User Code** is shown at the bottom of the screen.

---

## First-time Setup

### Step 1 — Tuya authentication

After saving the configuration and starting the add-on, open the **Log** tab. The add-on will print a Tuya QR code. Scan it with the Smart Life / Tuya Smart app to authorise the add-on. The add-on then fetches your homes and devices from the cloud.

### Step 2 — Matter pairing

Once devices are discovered the add-on prints a **Matter QR code** and a URL you can open to view it as an image. Use your Matter controller to add a new device and scan this code.

The Matter bridge uses the following static commissioning parameters:

| Parameter | Value |
|---|---|
| Passcode | `20202021` |
| Discriminator | `3840` |
| Port | `12356` |
| Vendor ID | `65521` |

Matter state is persisted to `/data/matter/`.

---

## Architecture

```
src/
├── index.ts                        NestJS bootstrap (port 13879)
├── const.ts                        Shared constants and env vars
├── controllers/
│   └── devices.controller.ts       HTTP GET / (stub, returns {})
├── services/
│   ├── Matter.ts                   Creates the Matter ServerNode + aggregator
│   ├── TuyaDeviceService.ts        Authenticates and emits TuyaDevice instances
│   └── Sync.ts                     Wires TuyaDevice → Tuya2Matter → Matter aggregator
└── libs/
    ├── tuyapi/
    │   ├── TuyaCloud.ts            Tuya Cloud REST client (AES-128-GCM signed requests)
    │   ├── TuyaLocal.ts            UDP discovery + TCP persistent connections
    │   ├── TuyaDevice.ts           Per-device state machine (RxJS BehaviorSubject)
    │   ├── DeviceMetadata.ts       Device config shape
    │   ├── MessageParser.ts        Tuya binary protocol encoder/decoder
    │   ├── cipher.ts               AES cipher helpers
    │   └── crc.ts                  CRC helpers
    ├── tuya2matter/
    │   ├── Tuya2Matter.ts          Mapper factory — routes by category, manages lifecycle
    │   ├── Tuya2MatterSwitch.ts    Switch / smart plug
    │   ├── Tuya2MatterCover.ts     Window covering / curtain
    │   ├── Tuya2MatterFan.ts       Fan with speed control
    │   ├── Tuya2MatterLock.ts      Door lock
    │   ├── Tuya2MatterAirSensor.ts Air quality sensor
    │   ├── Tuya2MatterBinarySensor.ts  Contact / door sensor
    │   ├── Tuya2MatterOccupancySensor.ts Presence / motion sensor
    │   ├── Tuya2MatterButton.ts    Wireless button
    │   └── Tuya2MatterTemperatureLight.ts  Colour-temperature light
    ├── vitural/
    │   └── VituralSwitch.ts        Matter-only virtual switch
    └── helpers/
        ├── LimitConcurrency.ts     Decorator to serialize async calls
        └── useObservable.ts        RxJS utility
```

### Key design patterns

- **RxJS throughout** — every device, connection, and state change is modelled as an Observable or BehaviorSubject. Reconnect logic, debouncing, and back-pressure are handled declaratively.
- **`TuyaDevice` as the boundary** — raw numeric DPS keys are translated to human-readable codes (`switch_1`, `fan_speed`, …) using a mapping fetched from the cloud at startup. All downstream code works only with readable codes.
- **Bridged endpoints** — each Tuya device becomes one Matter endpoint inside the aggregator. The `reachable` attribute of `BridgedDeviceBasicInformation` reflects the live TCP connection status.
- **Pending commands** — if a command arrives while the device is offline, it is stored in `TuyaDevice.$dps.pending` and flushed automatically when the local connection comes back online.

---

## Development

### Prerequisites

- [Bun](https://bun.sh) ≥ 1.0
- Node.js ≥ 18 (for type-checking)

### Running locally

```bash
cd tuya2matter/app
USER_CODE=<your_user_code> bun run src/index.ts
```

Add `test` as the first argument to limit LAN discovery to a single hard-coded device ID (useful for CI or offline testing):

```bash
USER_CODE=<code> bun run src/index.ts test
```

### Building (TypeScript compile check)

```bash
bun run build
```

### Docker / Home Assistant add-on

The `tuya2matter/Dockerfile` and `tuya2matter/config.yaml` define the HA add-on. The container requires `host_network: true` so that mDNS and UDP broadcasts work correctly.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `USER_CODE` | — | Tuya account user code (required) |
| `PORT` | `13879` | HTTP API port |
| `TUYA2MQTT_DEBUG` | `all` | Debug verbosity: `all`, device ID list, or empty |
| `VITURAL_SWITCHES` | — | Comma-separated virtual switch names |

---

## License

Apache 2.0 — see [`tuya2matter/app/LICENSE`](tuya2matter/app/LICENSE).
