# BenQ MoonHalo Bridge

Control the MoonHalo backlight of a BenQ RD280UG monitor from Hubitat and Google Home.

## What it is

The MoonHalo is the LED backlight on the rear of the BenQ RD280UG monitor. BenQ MoonHalo Bridge
exposes it to a Hubitat Elevation hub as a dimmable, color-temperature light. It has two parts:

- **Driver**: one Groovy file, installed on the Hub.
- **Bridge**: a Python service, installed on the Windows PC the monitor is connected to.

The Hub sends HTTP requests to the Bridge over the LAN. The Bridge converts each request into a
DDC/CI write to the monitor.

![The MoonHalo lit behind a BenQ RD280UG](docs/images/moonhalo-lit.jpg)

## Requirements

| Component | Requirement |
|---|---|
| Hub | Hubitat Elevation. Tested on a C-7, platform 2.4.3.177. |
| Monitor | BenQ RD280UG, connected to the PC by a DisplayPort or HDMI cable that carries DDC/CI. No other monitor is tested. |
| PC | Windows with Python 3.12 or later and the `py` launcher. Tested on Windows 11. |
| Network | Hub and PC on the same LAN. The Hub must reach TCP port 5000 on the PC. |
| Google Home (optional) | The [Google Home Community](https://github.com/mbudnek/google-home-hubitat-community) app. |

## Install

Install the Bridge, then the Driver. Each step is marked **PC** or **Hub**. For details of any PC
step, see the [Bridge README](Bridges/BenQ_MoonHalo/README.md).

1. **PC** - Clone the repository, or download and unpack the ZIP, and open the Bridge folder.

   ```
   git clone https://github.com/RBILLC/Hubitat.git
   cd Hubitat\Bridges\BenQ_MoonHalo
   ```

2. **PC** - Install the dependency (Flask).

   ```
   py -m pip install -r requirements.txt
   ```

3. **PC** - Create the configuration file.

   ```
   copy config.example.json config.json
   ```

   In `config.json`, set `allowed_ips`, `allowed_macs` and `hub_ip` to the Hub's IP and MAC
   address. The IP is on the Hub's **Settings > Hub Details** page. `arp -a` on the PC lists the
   MAC next to that IP.

4. **PC** - Confirm the Bridge detects the monitor.

   ```
   py -m moonhalo_bridge monitors
   ```

   Expected last line: `selected: BenQ RD280UG on \\.\DISPLAYn (by edid)`.

5. **PC** - Register and start the logon task. The script requests administrator approval,
   creates the scheduled task `MoonHaloBridge` and checks that the Bridge answers.

   ```powershell
   .\install_task.ps1
   ```

6. **PC** - Allow the Hub through Windows Firewall. Replace `192.168.1.10` with the Hub's IP. See
   [Windows Firewall rule](Bridges/BenQ_MoonHalo/README.md#windows-firewall-rule).

   ```
   netsh advfirewall firewall add rule name="MoonHalo Bridge (Hub)" dir=in action=allow protocol=TCP localport=5000 remoteip=192.168.1.10 profile=any
   ```

7. **Hub** - Import the Driver. Open **Drivers Code**, click **New Driver**, click **Import**,
   paste the URL, import, and click **Save**.

   ```
   https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy
   ```

8. **Hub** - Create the device. Open **Devices**, click **Add Device** > **Virtual**, enter a
   name, and select the type **BenQ MoonHalo Bridge**.

9. **Hub** - On the **Preferences** tab, enter the PC's IP in **Bridge IP address**. Change
   **Bridge port** only if the Bridge's `port` is not 5000. Click **Save Preferences**.

10. **Hub** - Verify on the **Commands** tab:

    - **On** lights the halo.
    - **Set Level** changes its brightness.
    - Under **Current States**, `bridgeLink` is `online` and `monitorLink` is `ok`.

![The device page on the Hub](docs/images/device-page.png)

## Usage

| Command | Behavior |
|---|---|
| `on` | Turns the halo on at the last level. The Bridge stores the level; the Hub does not send one. |
| `off` | Dims the halo to its lowest step, then turns it off. Level and color temperature are retained. |
| `setLevel(level, rate)` | Level 0 to 100. The halo moves to the nearest of its ten brightness levels; `level` reports the value sent. Level 0 is `off`. A level sent while the halo is off turns it on. |
| `setColorTemperature(kelvin, level, rate)` | The Bridge maps the Kelvin value to one of seven color steps between 2700 K and 6500 K. `colorTemperature` reports the Kelvin of that step: 2700 reports 2971. Turns the halo on if it is off, unless **Enable color pre-staging** is set. |
| `setColorTempStep(step)` | Sets the color step directly, 1 (warm) to 7 (cool). |
| `refresh` | Reads the Bridge's status. |
| `setBridgeAddress(ip, port)` | Called by the Bridge to announce its address. Can be run manually. |

**Transitions.** Every change is written as a sequence of hardware steps.

- With a rate: the rate is the total time of that change, in seconds.
- Without a rate: the **Default transition (ms)** preference applies. It is the time of a full
  brightness sweep, so a shorter change takes proportionally less time.
- A value of 0 applies the change at once.

## Google Home

Use the community [Google Home Community](https://github.com/mbudnek/google-home-hubitat-community)
app. It provides on/off, brightness, voice control and the white-temperature slider. Hubitat's
built-in Google Home app provides on/off and brightness only; it shows no color-temperature
control for color-temperature bulbs.

Setup procedure: [Google Home setup guide](docs/google-home-setup.md).

Device type settings in the community app:

| Setting | Value |
|---|---|
| Device type name | Bulb (any name) |
| Google Home device type | Light |
| Traits | On/Off, Brightness, Color Setting |
| Color Setting | **Color Temperature Control** only |
| Minimum / maximum color temperature | 2700 / 6500 |
| Color temperature attribute | `colorTemperature` |
| Set color temperature command | `setColorTemperature` |

![The device type in the Google Home Community app](docs/images/google-home-community-device-type.png)

![The device card in Google Home, with the white-temperature slider](docs/images/google-home-device-card.png)

Notes:

- After each move, the slider settles on the nearest of the seven color steps.
- Do not share the device through both apps.

## Configuration reference

### Preferences

| Preference | Default | Description |
|---|---|---|
| **Bridge IP address** | none | IPv4 address of the PC running the Bridge. Used until the Bridge announces its address. |
| **Bridge port** | 5000 | Port the Bridge listens on (`port` in `config.json`). |
| **Announce timeout (seconds)** | 200 | After the first announcement, the time without an announcement or a reply before the Bridge is marked offline. 0 disables the check. Set it above the Bridge's `announce_seconds`. |
| **Request timeout (seconds)** | 5 | Time to wait for the Bridge to answer a command before marking it offline. |
| **Poll interval** | 5 minutes | Status poll interval: disabled, or 1, 5, 10, 15 or 30 minutes. |
| **Enable color pre-staging** | off | Accept a color temperature while the halo is off without turning it on. |
| **Default transition (ms)** | 300 | Time of a full brightness sweep when a command carries no rate, 0 to 60000. 0 applies changes at once. Blank uses the Bridge's `transition_seconds`. |
| **Enable debug logging** | on | Writes debug lines to the hub log. Turns off after 30 minutes. |
| **Enable descriptionText logging** | on | Writes one info line to the hub log per change. |

The color temperature range is set on the Bridge: `kelvin_min` and `kelvin_max` in `config.json`,
default 2700 and 6500.

Address announcement (optional): the Bridge can report its current address to the Hub through the
Maker API, so the PC needs no DHCP reservation. See
[Letting the Hub find the Bridge](Bridges/BenQ_MoonHalo/README.md#letting-the-hub-find-the-bridge).

### Attributes

| Attribute | Values | Description |
|---|---|---|
| `switch` | `on`, `off` | State of the halo. |
| `level` | 0 to 100 | Level last commanded. 0 while the halo is off. |
| `colorTemperature` | Kelvin | Kelvin of the current color step. |
| `colorName` | text | Hubitat's name for that Kelvin, for example Soft White. |
| `bridgeLink` | `unknown`, `online`, `offline` | Whether the Hub reached the Bridge on its last attempt. While `offline`, `switch` and `level` keep their last values. |
| `monitorLink` | `unknown`, `ok`, `failed`, `unreachable` | Whether the Bridge reached the monitor on its last attempt. `failed` logs one warning; commands are still sent. `unreachable` is set while `bridgeLink` is `offline`. |
| `bridgeAddress` | `ip:port` | Address the Bridge last announced. |

### State variables

| Variable | Description |
|---|---|
| `bridgeVersion` | Version the Bridge reports with every reply. |
| `lastMonitorError`, `lastMonitorErrorAt` | Last DDC/CI error and its time. Retained after recovery. |
| `lastSeen`, `lastAnnounce` | Time of the last reply and of the last announcement. |
| `announcedIp`, `announcedPort`, `typedAddress` | The announced address and the address typed in the preferences. |

## What runs on the PC

The Bridge is Python source in
[`Bridges/BenQ_MoonHalo/moonhalo_bridge`](Bridges/BenQ_MoonHalo/moonhalo_bridge). Its only
dependency is Flask. It includes no compiled or third-party executable.

| Aspect | Behavior |
|---|---|
| Listening port | TCP 5000 by default. HTTP GET only. |
| Access control | Allowlist of the Hub's IP address and MAC address (resolved through the PC's ARP table), set in `config.json`. Other callers receive 403. Exceptions: requests from the PC itself (`allow_loopback`, default on) and `/health`, which is read-only. |
| Monitor writes | Two VCP registers on the RD280UG, identified by its EDID: one for power, one for brightness and color temperature. No other monitor and no other setting is written. |
| Network traffic | LAN only. No internet connection and no telemetry. |
| Process | A scheduled task in the logged-on user's session, without administrator rights. It starts at logon and stops at logoff. A Windows service is not used: services run in session 0, where the display functions are not documented to work. |
| Address announcement | Optional. With a Maker API token configured, the Bridge calls one command on one Hub device. The token is stored in `config.json` and is not logged. Without a token, the Bridge makes no outgoing calls. |
| Files written | `state.json` (last level and color step) and `bridge.log` (requests and monitor writes), in the Bridge folder. |

## Known limits and troubleshooting

- **Resolution**: ten brightness levels and seven color steps. This is a hardware limit; the steps
  are visible in a long transition.
- **Platform**: Windows only.
- **PC off or logged out**: `bridgeLink` is `offline`.
- **Monitor asleep**: commands are refused, `monitorLink` is `failed`, and `switch` is unchanged.
  Commands work again when the monitor wakes. No restart is needed.
- **Other monitors**: only the RD280UG is tested. For another MoonHalo monitor, set
  `monitor_product` in `config.json` to its EDID product code, which
  `py -m moonhalo_bridge monitors` prints.

For symptoms and fixes, see the
[troubleshooting table](Bridges/BenQ_MoonHalo/README.md#troubleshooting) in the Bridge README.

## Versions

| Part | Current version |
|---|---|
| Driver | 0.0.17 |
| Bridge | 0.0.12 |

- The Driver and the Bridge are versioned separately.
- The Driver requires Bridge 0.0.9 or later. An older Bridge is flagged in `bridgeVersion` and
  with one warning in the hub log.
- A Bridge newer than the Driver is compatible.
- Release notes: [GitHub Releases](https://github.com/RBILLC/Hubitat/releases).

To update:

- **Hub**: import the Driver again from the same URL and save.
- **PC**: pull the new code, then restart the task.

  ```
  schtasks /end /tn MoonHaloBridge
  schtasks /run /tn MoonHaloBridge
  ```

## Support

- Questions and discussion: Hubitat community forum thread, PLACEHOLDER-FORUM-THREAD-URL
- Bugs: [GitHub Issues](https://github.com/RBILLC/Hubitat/issues)
- Website: PLACEHOLDER-WEBSITE-URL

This is a community driver. It is not supported by Hubitat or BenQ.

## License

MIT. See [LICENSE.txt](LICENSE.txt).

---

Also in this repository: a Tuya TS0601 soil moisture sensor driver,
[`Drivers/Tuya_TS0601_Soil_Sensor_Driver.groovy`](Drivers/Tuya_TS0601_Soil_Sensor_Driver.groovy).
See [its forum thread](https://community.hubitat.com/t/156841).
