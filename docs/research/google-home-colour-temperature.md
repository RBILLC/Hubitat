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

## What the community integration's code does for a CT-only light [DOC: source read]

`google-home-community.groovy` (master, 5629 lines, read 2026-09-07):

- **SYNC** `attributesForTrait_ColorSetting`: with "Full-Spectrum Color Control" off and "Color Temperature Control" on it emits only `colorTemperatureRange: [temperatureMinK: <min>, temperatureMaxK: <max>]` from the two settings. No `colorModel`, so Google gets exactly the CT-only shape its docs (and Gemini) prescribe. Device type comes from the per-type "googleDeviceType" setting, so `LIGHT`.
- **QUERY** `deviceStateForTrait_ColorSetting`: `color: [temperatureK: device.currentValue(<colorTemperatureAttribute>)]`. `colorMode` is consulted only when both controls are on.
- **EXECUTE** `executeCommand_ColorAbsolute`: calls `device.<setColorTemperatureCommand>(temperature)` with the Kelvin Google sent, then polls up to 1 s (10 x 100 ms) for `colorTemperature == temperature`; if it never matches it answers `PENDING`, not an error, and Google follows up with QUERY. MoonHalo will always land here: the Driver replies asynchronously and the Bridge snaps Kelvin to one of seven hardware steps (5000 requested reads back 5143), so Google's slider will settle on the snapped value. Acceptable; no Driver change needed. Report State to Google is optional and needs a Google service-account JSON in the app.
- **Driver compatibility**: MoonHalo already has `setColorTemperature(value, level, tt)` with Kelvin first, `colorTemperature` attribute, `on`/`off`, `setLevel`. Nothing to add. Set the range to the Driver's 2700–6500 preferences.
- **Setup cost** (README): the user creates their own Google smart-home Action (README says console.actions.google.com; Google has since moved smart-home projects to the Google Home Developer Console, so the exact clicks need checking), OAuth account linking, fulfilment URL from the Hub UID, then pastes the app into Apps Code. Human-only steps; a `/wizard` candidate.

## Also checked: kkossev's Tuya Advanced Zigbee RGBW Bulb driver

`kkossev/Hubitat` development branch, 1856 lines, read 2026-09-07 at the user's suggestion. It contains no Google Home, Alexa or HomeKit handling. Its one relevant pattern is `installed()`, which pre-populates the full RGBW attribute set with placeholders before the bulb has reported anything: `colorMode CT`, `colorTemperature 2700`, `hue 0`, `level 0`, `saturation 0`, `switch off`, `healthStatus unknown`. That is the "populate the states so Google accepts the device" fix from t/149874 written into the driver, and it is for a device that genuinely has RGB. For MoonHalo it adds nothing: acceptance is already solved, and the attribute set it would produce (hue, saturation, colorMode) is the RGBW set, which the built-in app would type as a colour bulb. **[INFERENCE]** Presenting MoonHalo as RGBW to obtain a colour wheel that internally maps to colour temperature is possible (the Govee case shows the built-in app renders colour for RGBW devices) but contradicts the spec's "only standard capabilities, exactly on/off, brightness and colour temperature" and would show controls the hardware cannot honour; not recommended.

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

## Decisive test results, 2026-09-07 evening [OBSERVED]

1. Google-side refresh: MoonHalo removed from Google Home, re-added through Hubitat's Google Home app, "Hey Google, sync my devices". No colour-temperature control. Explanation 3 is ruled out.
2. Control device: "Hue filament bulb" (Apt Bedroom, `hueBridgeBulbCT`, state populated: colorTemperature 2890, colorName Soft White, networkStatus connected) shared through the built-in app. Accepted, but the Google Home tile has no colour-temperature control and renders exactly like MoonHalo. The same bulb linked through Hue's own Google Home integration shows the temperature-only picker (tap the colour control and only the white-temperature UI appears).
3. Second control device: a Hue colour bulb (`hueBridgeBulbRGBW`) shared through the built-in app shows no colour control of any kind in Google Home (user report; acceptance line in the hub log and populated hue/saturation not yet confirmed). If confirmed, the Govee report in t/147034 (colour adjustable in the app, 2024-12) no longer holds, and the current Google Home app renders nothing from the built-in app's legacy colour traits.

Conclusion: Hubitat's built-in Google Home app exposes no colour-temperature control for any device, including Hubitat's own CT driver. The `networkStatus`-vs-`connectionState` test is moot. User decision 2026-09-07: the community integration is rejected; the integration must work natively through the built-in app.

## Hubitat's own CT bulb driver compared [DOC: source read]

`hubitat/HubitatPublic/examples/drivers/advancedZigbeeCTbulb.groovy` (Mike Maxwell, 660 lines, read 2026-09-07): capabilities `Actuator`, `Switch`, `SwitchLevel`, `ChangeLevel`, `Bulb`, `Configuration`, `Color Temperature`; extra commands `flash`, `presetLevel`, `updateFirmware`; events `switch`, `level`, `colorTemperature`, `colorName` plus preference echoes. No `colorMode`, no `hue`, no `saturation`, no range attribute. That is the same Google-visible attribute set as `hueBridgeBulbCT` and as MoonHalo 0.0.7 (which adds only `connectionState`, shown harmless on 2026-09-04). Nothing in Hubitat's own CT driver reaches Google that MoonHalo does not already send. **[INFERENCE]** No driver change can produce the slider: the trait and range in the SYNC response are chosen by Hubitat's cloud, and Hubitat's own driver gets the same result.

## Native routes remaining

1. Voice through the legacy trait: "Hey Google, set MoonHalo to 4000 kelvin" / "make MoonHalo warmer"; check the hub log for `setColorTemperature`. Untested.
2. RGBW facade: only viable if an RGBW device shows a white-temperature section in the Google Home app through the built-in app. Test 3 above says it does not; pending confirmation of acceptance.
3. Hubitat updating the built-in app to Google's `ColorSetting` trait with `colorTemperatureRange` (the shape Hue's own integration sends). The only route to the Hue picker natively. Forum feature request to draft, citing t/147034 post 6 and tests 2 and 3.
