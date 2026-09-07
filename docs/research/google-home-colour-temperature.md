# Why Google Home Shows No Colour-Temperature Control for MoonHalo

Research date: 2026-09-07. Follows `google-home-device-mapping.md` (which got the device accepted). Labels: **[DOC]** official documentation, **[STAFF]** Hubitat staff forum post, **[FORUM]** community report, **[INFERENCE]** my reasoning, **[OBSERVED]** seen on this hub.

## Question

Driver 0.0.7 is accepted by Hubitat's built-in Google Home app and Google Home controls on/off and brightness, but shows no white (colour-temperature) slider. Why, and what is the shortest route to one?

## What is already true on this hub [OBSERVED]

- Attribute set: `switch`, `level`, `colorTemperature`, `colorName`, `connectionState`. Values populated (`colorTemperature 5143`, `colorName Daylight`, 2026-09-07 15:08 log). "Set colour temperature once so the state is populated" [FORUM, t/15874 and t/149874] is therefore already satisfied; in those threads it fixed *acceptance*, not the slider.
- Capabilities: `Switch`, `SwitchLevel`, `ColorTemperature`, `Bulb`, `Refresh`, `Actuator`; command `setColorTemperature` present. The community integration's requirement "SwitchLevel and ColorTemperature capabilities and the setColorTemperature command" is met.
- The hub's own `/hub2/devicesList` types the device `ColorTemperatureLight`, identical to Hubitat's `hueBridgeBulbCT` devices (2026-09-04 finding on issue #21).

## What Hubitat's built-in app sends to Google

**[STAFF]** Mike Maxwell, 2024-12-16, https://community.hubitat.com/t/147034 post 6, replying to a user who had noticed Google marks the `ColorSpectrum` and `ColorTemperature` traits deprecated: *"however deprecated isn't retired or removed, but maybe thats the issue as we are also using these older traits"*. So the built-in app's SYNC response uses Google's legacy `action.devices.traits.ColorTemperature`, not `ColorSetting`.

**[DOC]** https://developers.home.google.com/cloud-to-cloud/traits/colortemperature: *"This trait has been deprecated. Use ColorSetting instead."* Its SYNC attributes are `temperatureMinK` and `temperatureMaxK`, both optional. https://developers.home.google.com/cloud-to-cloud/traits/colorsetting gives the current form for a CT-only device: `"colorTemperatureRange": { "temperatureMinK": 2000, "temperatureMaxK": 9000 }`. Neither page says how the Google Home app renders each trait.

**[STAFF]** Mike Maxwell, 2019-04-19, https://community.hubitat.com/t/7227 post 7: *"Google is rather strict on attributes, so the devices are typed based on their attribute sets vs capabilities."* and *"The correct attribute name for adjustable white is colorTemperature."*

**[FORUM]** t/147034: Govee RGB+CT lights shared through the built-in app *can* be recoloured by voice and in the Google Home app; only Google *automations* fail. So the legacy ColorSpectrum trait still renders in the app for RGB devices. Whether the legacy ColorTemperature trait renders for a CT-only device is not reported anywhere found.

**[DOC]** https://docs2.hubitat.com/en/apps/google-home names "ColorTemperature bulbs" as supported and documents nothing about which controls appear.

## Where Gemini's advice applies

A SYNC response of type `LIGHT` with `OnOff`, `Brightness` and `ColorSetting` restricted to `colorTemperatureRange` is exactly what Google's docs prescribe [DOC]. Nothing on the hub can produce it through the built-in app: Hubitat's cloud builds the SYNC response and exposes no trait or range settings. The only place that response is configurable is the community integration (`mbudnek/google-home-hubitat-community`, README): "Color Temperature Attribute ... `colorTemperature` by default", "Minimum Color Temperature ... Default is 2200", "Maximum Color Temperature ... Default is 6500", "Set Color Temperature Command ... `setColorTemperature`", and "At least one of 'Full-Spectrum Color Control' and/or 'Color Temperature Control' must be set." It requires the user's own Google Actions project (console.actions.google.com, Smart Home, fulfilment URL built from the Hub UID, OAuth account linking) and is installed by pasting the app code; whether it coexists with the built-in app is not stated in the README.

## Ranked explanation [INFERENCE]

1. The built-in app emits the legacy ColorTemperature trait, possibly without `temperatureMinK`/`MaxK` (the driver has no attribute for the range; only preferences), and the current Google Home app does not render a white slider for that legacy trait on a CT-only device. Consistent with every observation; not provable from the hub.
2. The built-in app emits colour traits only when RGB attributes are also present (the Govee case works). Would mean no CT-only device gets a slider through the built-in app.
3. Google's stale device record. Each driver version changed the attribute set; if the device was not removed and re-added in Google Home after 0.0.6/0.0.7, Google still holds the earlier SYNC.

## Decisive test, in order

1. **Google-side refresh** [FORUM]: remove MoonHalo from the Google Home app, re-add it in Hubitat's Google Home app, then "Hey Google, sync my devices". Rules out 3 at no cost.
2. **Control device**: share one Hue White Ambiance bulb (driver `hueBridgeBulbCT`, attribute set `switch, level, colorTemperature, colorName, networkStatus`) through the built-in app. If it also shows no white slider, the built-in app cannot do it for any CT-only device and explanations 1/2 hold. If it does show one, the only difference from MoonHalo is `networkStatus` vs `connectionState`, and that becomes the next single-variable driver test.
3. **If the control bulb has no slider**: adopt the community integration. Its Color Temperature Control settings produce the `ColorSetting` + `colorTemperatureRange` SYNC that Gemini described; set the range to the driver's 2700-6500.

## Sources read

- https://community.hubitat.com/t/147034 (JSON; Mike Maxwell post 6, 2024-12-16)
- https://community.hubitat.com/t/7227 (JSON; Mike Maxwell posts 2, 5, 7)
- https://community.hubitat.com/t/149874 (JSON; Hue bulbs dropped, fixed by populating states)
- https://community.hubitat.com/t/15874 (JSON; Hue groups present as RGB, states workaround)
- https://community.hubitat.com/t/34957 (JSON; community integration announcement: motivation was blinds and fans reported as lights)
- https://developers.home.google.com/cloud-to-cloud/traits/colortemperature
- https://developers.home.google.com/cloud-to-cloud/traits/colorsetting
- https://raw.githubusercontent.com/mbudnek/google-home-hubitat-community/master/README.md
- Forum search.json queries on 2026-09-07 for colour-temperature-in-Google-Home reports: no thread found that reports a white slider appearing, or not appearing, for a CT-only Hubitat device through the built-in app.
