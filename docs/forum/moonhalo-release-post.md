# Draft forum post: [RELEASE] BenQ MoonHalo Bridge

Status: draft, 2026-10-09 (issue #50). Written as the 1.0.0 announcement and held until the 1.0.0 bump (#51) and the `v1.0.0` GitHub Release exist. To be posted by the user as michael.j.rothenberg. Category: **Custom Apps and Drivers**. One thread for the product's life: later versions are announced as replies and the first post is edited to stay current. Conventions: `docs/research/hubitat-release-post-conventions.md`.

Before posting, replace every `PLACEHOLDER-` token (the website URL and the release date), check that the three pictures in `docs/images/` are the real ones (see `docs/images/README.md`), and open every link in a private browser window. The optional video of the halo following the room's lights is hosted outside the repo and linked under the first screenshot (#52).

---

**Title:** [RELEASE] BenQ MoonHalo Bridge - the RD280UG's MoonHalo backlight in Hubitat and Google Home

**Body:**

# BenQ MoonHalo Bridge

Your monitor's backlight as a Hubitat bulb.

The BenQ RD280UG has an LED backlight on its rear, the MoonHalo. BenQ MoonHalo Bridge makes it a dimmable, color-temperature light on your hub, so rules, dashboards and Google Home can switch it, dim it and warm or cool it like any other bulb. Mine follows the room's lights in the evening.

It has two parts. The **Driver** is one Groovy file on the hub. The **Bridge** is a small Python service on the Windows PC the monitor is plugged into. The hub cannot reach a monitor by itself, so it sends short HTTP requests to the Bridge over the LAN, and the Bridge turns each one into a DDC/CI write to the monitor. No BenQ software and no third-party executable is involved.

![The MoonHalo lit behind a BenQ RD280UG](https://raw.githubusercontent.com/RBILLC/Hubitat/main/docs/images/moonhalo-lit.jpg)

![The device page on the hub](https://raw.githubusercontent.com/RBILLC/Hubitat/main/docs/images/device-page.png)

Version 1.0.0 (Driver 1.0.0, Bridge 1.0.0), released PLACEHOLDER-RELEASE-DATE. MIT licensed. This is a community driver: it is not supported by Hubitat or by BenQ. Contact @michael.j.rothenberg for support. Use it at your own risk.

## Features

- On and off, with the halo dimming out and rising instead of snapping
- Level, on the halo's ten brightness levels
- Color temperature, 2700 K to 6500 K on the halo's seven color steps
- Transitions: a rate from a rule is honored as the total time, and a preference sets the default pace
- Google Home with the white-temperature slider and voice, through the Google Home Community app
- `bridgeLink` (`unknown`, `online`, `offline`) shows whether the hub can reach the PC, and `monitorLink` shows whether the PC can reach the monitor
- The Bridge can announce its own address to the hub, so a PC on DHCP needs no reservation

## Requirements

- A Hubitat Elevation hub. Tested on a C-7, platform 2.4.3.177.
- A BenQ RD280UG, connected to the PC over a cable that carries DDC/CI. Most DisplayPort and HDMI cables do.
- A Windows PC with Python 3.12 or later. Tested on Windows 11.
- The hub and the PC on the same LAN. The hub must reach TCP port 5000 on the PC.

## Installation

The README has the full numbered steps, each tagged PC or Hub: https://github.com/RBILLC/Hubitat#install

**1. Bridge on the PC**

1. Clone or download https://github.com/RBILLC/Hubitat and open `Bridges\BenQ_MoonHalo`.
2. `py -m pip install -r requirements.txt`
3. Copy `config.example.json` to `config.json` and put your hub's IP and MAC address in the allowlist.
4. `py -m moonhalo_bridge monitors` should end with `selected: BenQ RD280UG ... (by edid)`.
5. Run `.\install_task.ps1` to start the Bridge at logon, and allow the hub through Windows Firewall.

The Bridge README is the PC manual: https://github.com/RBILLC/Hubitat/blob/main/Bridges/BenQ_MoonHalo/README.md

**2. Driver on the hub**

1. **Drivers Code** > **New Driver** > **Import**, paste this URL, import and **Save**:
   `https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy`
2. **Devices** > **Add Device** > **Virtual**, type **BenQ MoonHalo Bridge**.
3. Set **Bridge IP address** to the PC's address and **Save Preferences**.
4. Click **On**. The halo lights, and `bridgeLink` reads `online`.

**Hubitat Package Manager**

Not yet. The install is a manual import for now. I will add an HPM package if there is interest.

**Updating**

Driver: import again from the same URL. Bridge: pull the new code and restart the `MoonHaloBridge` task. The two are versioned separately, and the device page shows the Bridge's version and flags one that is too old for the Driver.

## Google Home

Hubitat's built-in Google Home app accepts the device and gives on/off and brightness, but it shows no color-temperature control for any color-temperature bulb. The community Google Home Community app does. It needs a one-time setup on the Google side and one device type on the hub. The step-by-step guide with screenshots: https://github.com/RBILLC/Hubitat/blob/main/docs/google-home-setup.md

![The device card in Google Home, with the white-temperature slider](https://raw.githubusercontent.com/RBILLC/Hubitat/main/docs/images/google-home-device-card.png)

## What runs on the PC

A program on your PC that takes commands from the network deserves a plain answer, so here it is.

- The Bridge is plain Python you can read, with Flask as its one dependency. Nothing is compiled and nothing is downloaded at run time.
- It listens on one port, TCP 5000 by default.
- It answers only callers in its allowlist, checked by your hub's IP address and MAC address. Everyone else gets a 403.
- It writes two DDC/CI registers on one monitor, the RD280UG, found by its EDID identity. It changes nothing else on the monitor or the PC.
- Nothing leaves your LAN. It makes no internet connection and sends no telemetry.
- It runs as your own user in a logon scheduled task, without administrator rights. A Windows service runs in session 0, where the display functions are not documented to work.
- The address announcement is optional. It uses a Maker API token that stays in `config.json` on the PC.

## Known limits

- The halo has ten brightness levels and seven color steps. That is the monitor's hardware, so a long transition shows the steps.
- Windows only.
- The halo follows the PC. With the PC off or nobody logged in, the device shows `bridgeLink` `offline`, like a bulb with no power.
- While the monitor sleeps, commands are refused and the device says so. The next command after it wakes works.
- The RD280UG is the only monitor I have tested.

## Links

- GitHub: https://github.com/RBILLC/Hubitat
- Releases and release notes: https://github.com/RBILLC/Hubitat/releases
- Bridge README: https://github.com/RBILLC/Hubitat/blob/main/Bridges/BenQ_MoonHalo/README.md
- Issues: https://github.com/RBILLC/Hubitat/issues
- Website: PLACEHOLDER-WEBSITE-URL

## Feedback

Do you own another BenQ monitor with a MoonHalo? I would like to hear whether it works. Run `py -m moonhalo_bridge monitors` and post the `product` code it prints for your monitor (the RD280UG's is `BNQ80BB`); the Bridge takes that code as one line of configuration.

Please report bugs on GitHub Issues, and use this thread for questions and discussion.

-- michael.j.rothenberg
