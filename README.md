# Hubitat

Custom Hubitat Elevation drivers and their companion PC-side bridges. A driver here is one
Groovy file installed on the Hub; a bridge is a small helper service on another machine, used
when the Hub cannot talk to a device directly.

## Drivers

- **Tuya TS0601 Soil Moisture Sensor** (`Tuya_TS0601_Soil_Sensor_Driver.groovy`) — reads soil
  moisture, soil temperature, illuminance, and battery from a Tuya TS0601 Zigbee soil sensor.
  Import URL: `https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/Tuya_TS0601_Soil_Sensor_Driver.groovy`
- **BenQ MoonHalo Bridge** (`BenQ_MoonHalo_Bridge_Driver.groovy`) — presents the MoonHalo
  backlight of a BenQ RD280UG monitor as a dimmable, colour-temperature light, driven over HTTP
  by the BenQ MoonHalo Bridge below.
  Import URL: `https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy`

## Bridges

- **BenQ MoonHalo Bridge** (`Bridges/BenQ_MoonHalo/`) — a Python HTTP service for the Windows PC
  the monitor is attached to; it turns Hub requests into DDC/CI writes. See
  [`Bridges/BenQ_MoonHalo/README.md`](Bridges/BenQ_MoonHalo/README.md) for installation,
  configuration, and running it as a Windows service.

## Installing a driver

1. In the Hubitat web console, go to **Drivers Code**.
2. Click **New Driver**.
3. Click **Import**, paste the driver's import URL from the list above, and import it.
4. Click **Save**.
5. Go to **Devices**, click **Add Device** > **Virtual**, give it a name, and set its type to
   the driver you just imported.
6. Open the new device and set its preferences.

### BenQ MoonHalo Bridge preferences

- **Bridge IP address (initial)** and **Bridge port (initial)** — where the Bridge listens
  (default port 5000). Once the Bridge has announced its own address (see below) these are
  used again only after you retype them, until the next announcement.
- **Announcement timeout (seconds)** — once the Bridge has announced its address, how long the
  Hub waits without hearing from it (no announcement and no reply) before marking it offline
  (default 200, three missed minutes; 0 disables the check). Must exceed the Bridge's
  `announce_seconds`. Until the first announcement ever arrives, only the status poll judges
  the Bridge.
- **Request timeout (seconds)** — how long the Hub waits for the Bridge before treating it as
  offline.
- **Poll interval** — how often the Hub asks the Bridge for its status when no command has been
  sent (disabled, or every 1, 5, 10, 15, or 30 minutes).
- **Warm colour temperature (Kelvin)** and **Cool colour temperature (Kelvin)** — the ends of the
  colour temperature slider.
- **Enable color pre-staging** — store a colour temperature while the MoonHalo stays off,
  instead of turning it on.
- **Default transition (seconds)** — how long a full brightness sweep takes when a command
  carries no rate of its own (0 to 60; 0 snaps). Every move runs at that pace, so a short move
  finishes sooner. Blank (the default) sends nothing and the Bridge's own `transition_seconds`
  applies. A rate passed to setLevel or setColorTemperature still means the total time for that
  move and wins.
- **Enable debug logging** and **Enable description text logging** — as in Hubitat's other
  drivers; debug logging turns itself off after 30 minutes.

#### Letting the Bridge announce its address

The PC's address can change (DHCP, joining or leaving a VPN). Instead of a DHCP reservation,
the Bridge announces its current LAN address to the Hub through the **Maker API** app: it
calls the Driver's `setBridgeAddress(ip, port)` command when it starts, every minute, and
within a few seconds of its address changing. The Driver stores the announced address, shows it
in the `bridgeAddress` attribute as `ip:port`, prefers it over the typed preferences, and marks
`connectionState` offline when nothing has been heard from the Bridge for longer than the
announcement timeout (one warning in the log, then debug lines). Retyping the IP or port
forgets the announced address until the next announcement; saving other preferences keeps it.
The command is meant for the Bridge, but it can be run from the device page to point the
Driver at an address by hand. The Maker API setup is described in the Bridge README's
"Letting the Hub find the Bridge" section.

The PC side — installing and running the Bridge itself, its configuration file, and its
allowlist — is covered in [`Bridges/BenQ_MoonHalo/README.md`](Bridges/BenQ_MoonHalo/README.md).

### Google Home

Hubitat's built-in **Google Home** app accepts the MoonHalo and gives on/off and brightness,
but no colour-temperature control: as of September 2026 it exposes none for any
colour-temperature bulb, including Hubitat's own Zigbee and Hue drivers (see
`docs/research/google-home-colour-temperature.md`). For the white-temperature slider, share the
device through the community **Google Home Community** app instead (install from Hubitat Package
Manager; setup in its README at https://github.com/mbudnek/google-home-hubitat-community) with a
device type defined as:

- **Device type**: Bulb (or Color Temperature); **Google Home device type**: Light.
- **Traits**: On/Off and Brightness with their defaults; Color Setting with only
  **Color Temperature Control** set, minimum **2700**, maximum **6500**, attribute
  `colorTemperature`, command `setColorTemperature`.

Do not share the MoonHalo through both apps at once. The slider settles on the nearest of the
halo's seven colour steps after each move, which is expected.
