# Draft GitHub release notes: v1.0.0

Status: draft, 2026-10-09 (issue #50). For the GitHub Release the user publishes on tag `v1.0.0`, after the 1.0.0 bump (#51). Replace every `PLACEHOLDER-` token before publishing (the forum thread URL and the website URL). Release title: `BenQ MoonHalo Bridge 1.0.0`.

---

**Body:**

## BenQ MoonHalo Bridge 1.0.0

The first public release. BenQ MoonHalo Bridge makes the MoonHalo backlight of a BenQ RD280UG monitor a dimmable, color-temperature light on a Hubitat Elevation hub, for rules, dashboards and Google Home.

It ran on the author's hub and PC as 0.0.x from September 2026. 1.0.0 is the same code, verified end to end against the [release checklist](https://github.com/RBILLC/Hubitat/blob/main/docs/release-checklist.md) and documented for other people to install.

### The two parts

| Part | Version | Where it runs |
|---|---|---|
| Driver, `Drivers/BenQ_MoonHalo_Bridge_Driver.groovy` | 1.0.0 | The Hubitat hub |
| Bridge, `Bridges/BenQ_MoonHalo` | 1.0.0 | The Windows PC the monitor is plugged into |

### What it does

- On, off, level and color temperature, with transitions that ramp through the halo's steps
- Google Home with the white-temperature slider, through the Google Home Community app
- `bridgeLink` and `monitorLink` attributes that say whether the PC and the monitor can be reached
- An allowlisted, LAN-only Bridge that runs as a logon task and writes two DDC/CI registers on one monitor

### Install

Follow the [README](https://github.com/RBILLC/Hubitat#install): the Bridge on the PC first, then the Driver on the hub.

- Driver import URL: `https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy`
- PC manual: [Bridge README](https://github.com/RBILLC/Hubitat/blob/main/Bridges/BenQ_MoonHalo/README.md)
- Google Home: [setup guide](https://github.com/RBILLC/Hubitat/blob/main/docs/google-home-setup.md)

Requirements: a Hubitat Elevation hub (tested on a C-7, platform 2.4.3.177), a BenQ RD280UG over a cable that carries DDC/CI, and a Windows PC with Python 3.12 or later on the same LAN.

### Compatibility

The Driver and the Bridge are versioned separately, and each moves only when it changes. The Driver names the oldest Bridge it can work with, shows the Bridge's version on the device page, and flags one that is too old. A Bridge newer than the Driver always works. Driver 1.0.0 works with Bridge 0.0.9 or later; install the two 1.0.0 parts together and there is nothing to check.

### Known limits

Ten brightness levels and seven color steps, which are the monitor's own. Windows only. The RD280UG is the only tested monitor.

### Support

Questions and discussion: the forum thread, PLACEHOLDER-FORUM-THREAD-URL. Bugs: [GitHub Issues](https://github.com/RBILLC/Hubitat/issues). Website: PLACEHOLDER-WEBSITE-URL.

MIT licensed.
