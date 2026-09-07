# Draft forum post: Google Home integration and colour-temperature control

Status: draft, 2026-09-07. To be posted by the user. Suggested category: **Feedback** (community.hubitat.com/c/feedback, "Share your feedback and ideas about Hubitat Elevation"); **Built-In Apps and Drivers** is the alternative. Evidence: `docs/research/google-home-colour-temperature.md`.

---

**Title:** Google Home integration: no colour-temperature control for CT bulbs in the Google Home app (ColorSetting trait?)

**Body:**

I have been trying to get a white/colour-temperature control for a CT-only bulb in the Google Home app through the built-in Google Home integration, and after a day of controlled tests I think the limitation is in the integration's SYNC response rather than in any driver. Posting the evidence in case it helps, and to ask whether a move to Google's current `ColorSetting` trait is on the roadmap.

**What I see (hub 2.4.x, Google Home app on Android, September 2026):**

Every device below is accepted by the integration, shows up in Google Home, and can be switched and dimmed. None of them shows a colour-temperature (white) control, by tile or by tapping into the device:

- Hue White Ambiance bulb via the built-in Hue Bridge Integration (`hueBridgeBulbCT`), colorTemperature and colorName populated.
- Hue colour bulb via the Hue Bridge Integration (`hueBridgeBulbRGBW`): no colour control at all, not even the colour wheel.
- A Zigbee CT bulb paired directly, on the **Advanced Zigbee CT Bulb** driver.
- A custom CT-only driver with the same attribute set as Advanced Zigbee CT Bulb (switch, level, colorTemperature, colorName).

Control: the *same* Hue White Ambiance bulb linked to Google through Hue's own integration shows the normal white-temperature picker (tap the colour control and only the temperature UI appears). So the phone and the Google account are fine; the difference is what each integration tells Google.

Removing and re-adding the devices and "Hey Google, sync my devices" made no difference.

**Why I think it is the trait:**

In https://community.hubitat.com/t/147034 (Dec 2024) @mike.maxwell mentioned the integration still uses the older `ColorSpectrum` / `ColorTemperature` traits. Google's docs mark `action.devices.traits.ColorTemperature` deprecated ("This trait has been deprecated. Use ColorSetting instead", https://developers.home.google.com/cloud-to-cloud/traits/colortemperature) and describe the current form for a CT-only light as `ColorSetting` with `colorTemperatureRange: { temperatureMinK, temperatureMaxK }` (https://developers.home.google.com/cloud-to-cloud/traits/colorsetting). I cannot see the SYNC payload from the hub side, so this is inference, but it is consistent with every result above and with the Hue comparison.

**Ask:**

Would it be possible for the integration to emit `ColorSetting` (with `colorTemperatureRange`, and `colorModel`/`colorTemperatureRange` for RGBW) instead of the deprecated traits? A fixed default range such as 2000-6500 K would already produce the picker; drivers do not expose a range attribute today, so that seems the simplest first step.

Happy to run any test that helps. Debug logs from the hub-side app are available on request.
