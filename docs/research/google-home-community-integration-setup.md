# Setting Up the Community Google Home Integration for MoonHalo

Research date: 2026-09-07. Follows `google-home-colour-temperature.md` (which concluded that Hubitat's built-in Google Home app cannot show a colour-temperature control for any device, and that the user has decided to adopt `mbudnek/google-home-hubitat-community` for the MoonHalo driver). This document is the setup reference for that adoption, precise enough to script an interactive wizard. Labels: **[DOC]** official documentation, **[STAFF]** Hubitat staff forum post, **[FORUM]** community report (the integration's own author, `mbudnek`, is a repo owner/maintainer, not Hubitat staff — his posts are labelled **[FORUM: author]**), **[INFERENCE]** my reasoning, **[OBSERVED]** seen on this hub.

Target device: `Drivers/BenQ_MoonHalo_Bridge_Driver.groovy` — capabilities `Switch`, `SwitchLevel`, `ColorTemperature`, `Bulb`; attributes `switch`, `level`, `colorTemperature`, `colorName`, `connectionState`; command `setColorTemperature(kelvin, level, tt)`; Kelvin range 2700–6500.

## 1. README installation steps vs. the current Google Home Developer Console

### 1a. The README, quoted verbatim [DOC: source read]

`https://raw.githubusercontent.com/mbudnek/google-home-hubitat-community/master/README.md` (465 lines, read 2026-09-07):

**Installing the Hubitat App:**

> 1. Navigate to "Apps Code" in Hubitat
> 2. Click "New App"
> 3. Paste the code from [google-home-community.groovy](google-home-community.groovy) into the editor and click save
> 4. Click "OAuth"
> 5. In the popup dialog, click "Enable OAuth in App"
> 6. Click "Update"
> 7. Click "OAuth" again
> 8. Make a note of the values in the "Client ID" and "Client Secret" fields
>     - Note: Using keyboard shortcuts to copy from the Client ID and Client Secret fields doesn't work in some browsers (notably Google Chrome). You may need to either right-click and copy from the context menu or type the values out manually.
> 9. Navigate to "Apps" in Hubitat
> 10. Click "Add User App" and select "Google Home Community"
> 11. Make a note of the app's ID. This can be found in your web browser's URL bar.
>     - The URL should be `http://{your hub IP}/installedapp/configure/{app ID}/mainPreferences`
>     - The number between "configure/" and "/mainPreferences" is your app's ID
> 12. Configure at least one device type. See Configuring Devices below.
> 13. Click "Done".

**Creating the Google smart home Action** (this is the section that is stale — see 1b):

> Before creating your Google smart home Action, you will need your Hubitat hub's ID:
> 1. Navigate to the "Settings -> Hub Details" page in Hubitat
> 2. Note the value under "Hub UID"
>
> To create your Google smart home Action:
> 1. Navigate to https://console.actions.google.com
> 2. Click "New project"
> 3. Enter a name for the project and click "Create project"
> 4. Select "Smart Home" and click "Start Building"
> 5. Click the "Develop" tab.
> 6. On the "Invocation" screen, give your Action a name
> 7. Click "Actions" in the menu
> 8. Enter the following as the Fulfillment URL:
>     - `https://cloud.hubitat.com/api/{your hub ID}/apps/{app ID}/action`
> 9. Click "Account linking" in the menu
> 10. Enter the Client ID and Client Secret you got when enabling OAuth for the Google Home Community app
> 11. Enter `https://oauth.cloud.hubitat.com/oauth/authorize` as the Authorization URL
> 12. Enter `https://oauth.cloud.hubitat.com/oauth/token` as the Token URL
> 13. Click "Next"
> 14. Leave everything unchecked in the "Use your app for account linking (optional)" section and click "Next"
> 15. In the "Configure your client (optional)" section, enter "app" in the Scopes box
> 16. Click "Save"
> 17. Click the "Test" tab
> 18. In the top-right of the page, click "Settings" and ensure "On device testing" is enabled
> 19. Open the Google Home app on your phone or tablet
> 20. Tap the "+" in the top-left corner
> 21. Tap "Set up device"
> 22. Tap "Works with Google"
> 23. In the list, find the entry `[test] {your action name}`
> 24. Enter your Hubitat account credentials and click "Sign In"
> 25. Select your hub and tap "Select"
> 26. Make sure at least one device is selected to expose to Google Home
> 27. Tap "Authorize"

`console.actions.google.com` (the old Actions on Google console) is gone for this purpose. Google's own migration page confirms it **[DOC]**, `https://developers.home.google.com/cloud-to-cloud/project/migration` (read 2026-09-07, server-rendered, full text retrieved):

> "The Actions on Google Console is deprecated. As of December 2024, all smart home projects that were set up in the Actions Console have been migrated to the Google Home Developer Console. ... All smart home projects in the Actions Console are now view-only. Your smart home Actions on Google projects are now called 'Cloud-to-cloud integrations' to support our expanding ecosystem."

### 1b. Mapping each README step to the current console

Two sources map the old flow to the new one exactly:

**[FORUM: author]** `mbudnek`, https://community.hubitat.com/t/34957/1160 (undated post, thread context places it December 2024, replying to a user stuck at "conversation actions"):

> "Smart Home actions are still fully supported. I haven't updated the instructions for Google's new Developer Console that replaced the old Actions Console, but it's fairly similar. The basic flow is to go to 'Cloud to Cloud -> Develop -> Add Integration -> Next -> Next'. All of the account linking and fulfillment URL options are there. The biggest change is that you have to select all of the supported device types, but you can just select all of them (ctrl+a in the dropdown will select everything)."

**[DOC]** `https://developers.home.google.com/cloud-to-cloud/project/create` and `.../cloud-to-cloud/integration/create` (both read 2026-09-07, server-rendered by curl with a browser `User-Agent`, so this is real page text, not a JS-shell placeholder). Combined, current step-by-step:

1. **Create a developer project** (replaces README steps 1–3, "New project"):
   - Go to `https://console.home.google.com`
   - On the "Manage projects" page, click **"Create a project"**
   - On the "Get started" page, click **"Create project"**
   - Enter the project name (guidance: incorporate your company/project name, keep it unique, don't use "test" in the name) and click **"Create new project"** — you land back on the **"Home"** page for the new project.
   - **[DOC]** naming guidance: "Use your company name", "Use the type of project or action in the name", "Don't use 'test' in the project name."

2. **Add the Cloud-to-cloud integration** (replaces README steps 4–6, "Select Smart Home", "Develop tab", "Invocation"):
   - From the project's "Home" page, click **"Open"**, then **"Add cloud-to-cloud integration"**.
   - First time in a project, you land on a **"Resources"** page; click **"Next: Develop"**, which shows a **"Checklist"** page; click **"Next: Setup"**.
   - You arrive at the **"Setup & configuration"** page. Enter the integration name here (this replaces "give your Action a name").

3. **App branding** (new requirement, not in the README): upload a 144×144 pixel PNG icon. **[DOC]**: "A round logo is required... If the logo is transparent, a white background with a colored border is required."

4. **Account linking section** (replaces README steps 9–16, "Account linking"): on the same "Setup & configuration" page, in the **"Account linking"** section, enter the OAuth settings. The current docs describe the *concept* (`.../cloud-to-cloud/primer/account-linking`, `.../cloud-to-cloud/project/authorization`) but the field-by-field page (the actual console form) was not retrievable as static text beyond "configure your app to allow logins from Google Accounts" — see the gap noted below. **[FORUM: author]** confirms the fields still exist: "All of the account linking and fulfillment URL options are there." Given the field values are unchanged endpoints (Hubitat's cloud OAuth server, not Google's), the README's exact values still apply:
   - Client ID / Client Secret: from the app's "OAuth" popup in Apps Code (README steps 4–8)
   - Authorization URL: `https://oauth.cloud.hubitat.com/oauth/authorize`
   - Token URL: `https://oauth.cloud.hubitat.com/oauth/token`
   - Scopes: `app`

5. **Cloud fulfillment URL section** (replaces README step 8): **[DOC]** "In the 'Cloud fulfillment URL' section, provide the fulfillment URL used to process smart home intents." Same URL as before: `https://cloud.hubitat.com/api/{hub UID}/apps/{app ID}/action`.

6. **Device type selection** (new requirement not in the README): **[DOC]** "Click 'Select device type' and select the device type from the drop-down menu." **[FORUM: author]**: "the biggest change is that you have to select all of the supported device types, but you can just select all of them (ctrl+a in the dropdown will select everything)."

7. **Save**: **[DOC]** "Click 'Save', which saves the Cloud-to-cloud integration configuration."

8. **Testing / linking to your own Google account** (replaces README steps 17–27): the README's "Test tab -> Settings -> On device testing" toggle is gone; the equivalent current concept is described at `.../cloud-to-cloud/test` (see Question 5 below) plus the same Google Home app flow: open the Google Home app, tap **"+"**, **"Set up device"**, **"Works with Google"**, search for the `[test] {integration name}` entry. This exact final step was not independently re-confirmed post-migration by a primary source (see gap below), but `https://docs2.hubitat.com/en/apps/google-home` **[DOC]** shows the still-current wording for the *built-in* app's equivalent flow ("Select Set up device. Select Works with Google. Search for and select Hubitat."), which is strong circumstantial evidence the wording is unchanged for third-party actions too.

### 1c. Gaps in this section

- The exact current field labels inside the "Account linking" section of "Setup & configuration" (i.e., whether the console still literally says "Client ID" / "Client Secret" / "Authorization URL" / "Token URL" / "Scopes", or has renamed them) were not retrievable — `https://developers.home.google.com/cloud-to-cloud/integration/account-linking` and several other guessed URLs 404, and the pages that exist (`primer/account-linking`, `project/authorization`) are conceptual, not a field-by-field console walkthrough. **[INFERENCE]**: OAuth authorization-code fields are a standard Google Home Developer Console form and very unlikely to differ from the terms in `project/authorization`'s own parameter tables (`client_id`, `client_secret`, "authorization endpoint", "token exchange endpoint", `scope`), so the README's four fields are the right ones to fill in; exact on-screen labels should be confirmed by screenshot when the wizard runs.
- GitHub issue #117 (`ryancasler`, 2025-02-23, https://github.com/mbudnek/google-home-hubitat-community/issues/117) confirms a user hit the new console after a straightforward migration attempt ("Also the whole Google Console Setup has completely changed since actions are now set up in the developer console") but the issue does not document the new steps — the user got it working by "restart[ing] from the beginning," and the issue was closed without further detail.

## 2. How the fulfilment/OAuth URLs are built, and OAuth-in-Apps-Code requirement

**[DOC: source read]** `google-home-community.groovy` (5629 lines) defines exactly one mapped endpoint:

```groovy
mappings {
    path("/action") {
        action: [
            POST: "handleAction"
        ]
    }
}
```

This is the only app-defined HTTP path. Combined with Hubitat's cloud endpoint convention `https://cloud.hubitat.com/api/{hubUID}/apps/{appId}/`, the fulfilment URL is `https://cloud.hubitat.com/api/{hubUID}/apps/{appId}/action` — exactly what the README says, and unaffected by the Google console migration since it's entirely a Hubitat-side URL.

There is no app-defined `/oauth` or `/token` mapping in the source; those are Hubitat's own cloud OAuth server (`oauth.cloud.hubitat.com`), which every OAuth-enabled Hubitat app shares by convention — confirmed by the README's fixed values `https://oauth.cloud.hubitat.com/oauth/authorize` and `https://oauth.cloud.hubitat.com/oauth/token`, unrelated to the app's own code.

**OAuth must be enabled for the app.** Two independent confirmations:
- README steps 4–8 (Apps Code -> "OAuth" -> "Enable OAuth in App" -> "Update").
- **[DOC: source read]** `packageManifest.json` (fetched from the repo root) declares it structurally: `"apps": [{"id": "b2ff1880-4b4c-4b1d-81d7-fce0ced1044a", "name": "Google Home Community", "namespace": "mbudnek", "location": "...google-home-community.groovy", "required": true, "oauth": true}]` — the `"oauth": true` flag is how Hubitat Package Manager knows to prompt for/enable OAuth on install (see Question 6).

**Hubitat's own developer docs on app OAuth/cloud endpoints**: not found. `docs2.hubitat.com` is server-rendered for content pages that exist (`en/apps/google-home` loaded fine, see Question 1), but every guessed developer-oauth path 404'd (`en/developer/apps/app-oauth`, `en/developer/oauth`, `en/developer/cloud-oauth`, `en/developer/cloud`, `en/developer/using-cloud-api`, `en/developer/cloud-endpoints`, `en/developer/using-oauth-in-a-hubitat-app`, `en/apps/apps-code`, `en/developer/apps` — all checked 2026-09-07). No sitemap.xml either. This is a genuine gap: rely on the README and the source, as anticipated.

## 3. Coexistence with the built-in Google Home app

Both a caution and a success report exist, from the same thread, four minutes apart, in the integration's original 2020 announcement:

**[FORUM: author]** `mbudnek`, https://community.hubitat.com/t/34957/6 (2020-02-24):
> "Hubitat doesn't seem to like having multiple Google integrations registered at the same time. You may have to un-link the official Hubitat integration before linking your new one."

**[FORUM]** `cometfish`, https://community.hubitat.com/t/34957/9 (2020-02-25), after working around the initial linking failure:
> "I got it to link - skipped to the next part, and created an actual device in the Google Home Community app in Hubitat. Then the Google Home app linked with it, and listed it under Linked Services. It does not seem to mind having both the inbuilt Hubitat GH and your GH app (I labeled it SmartHome in the pic) running at the same time 🙂 And the door sensor works great!"

His preceding post makes clear this was with **non-overlapping devices**: "I was hoping to have both linked side by side, at least initially (**not with the same devices**)." That matches the README's own within-app rule ("Note: The same device should not be selected for multiple device types") extended to a second app.

Net answer: coexistence is possible — both integrations can be linked to the same Google account simultaneously — but (a) the initial *linking* step may need to be retried or may briefly require the built-in integration unlinked if Google's account-linking flow chokes on the second OAuth client, and (b) a given device should be exposed through only one of the two integrations at a time, not both, to avoid duplicate Google Home entries. For MoonHalo specifically: since it is only shared through the built-in app today (per `google-home-colour-temperature.md`), the clean path is to remove MoonHalo from the built-in app's device list (not necessarily unlink the whole built-in integration) before adding it to the community app's device type, then re-sync.

No post-2024-migration report of this specific coexistence question was found (searches for "built-in", "both apps", "duplicate", "same time" combined with the thread or the GitHub issues turned up nothing newer than the 2020 exchange above) — the 2020 evidence is the primary source available, labelled and dated accordingly. **[INFERENCE]**: the underlying constraint (Hubitat's cloud OAuth server, one client credential per app) has not changed with Google's console migration, so this guidance should still hold, but it has not been independently re-confirmed since 2020.

## 4. Defining a device type for a CT-only light

**[DOC: source read]**, from the README's "Defining a Device Type" and "Device Type Settings" sections and the groovy source's `deviceTypePreferences` page:

- **Steps**: Apps -> "Google Home Community" app -> "Define new device type" -> fill in "Device Type Definition" page -> select traits -> "Next" -> back on main page, click "{device type} devices" and select which Hubitat devices use this type -> "Done" -> pull-to-refresh in Google Home app or say "Hey Google, sync my smart home devices".
- **Device type name**: free-text display name (shown in the device selector).
- **Device type** (Hubitat capability filter, README: "A Hubitat capability that will determine which devices are available to select for this device type"). **[DOC: source read]**, `HUBITAT_DEVICE_TYPES` enum in the groovy source includes `colorTemperature: "Color Temperature"` — the correct choice for MoonHalo (capability `ColorTemperature`).
- **Google Home device type** (README: "The type of device that Google Home will see the selected devices as. Controls the icon and available controls in the Google Home app..."). **[DOC: source read]**, `GOOGLE_DEVICE_TYPES` enum includes `LIGHT: "Light"` — shown to the user in the dropdown as **"Light"**, sent to Google as `action.devices.types.LIGHT`.
- **Device traits** needed: **On/Off** and **Brightness** (for switch/level) plus **Color Setting** with only "Color Temperature Control" checked (not "Full-Spectrum Color Control", since MoonHalo has no hue/saturation).
  - **On/Off**: "On/Off Attribute... Maps to the `switch` attribute by default"; "Control Type: Separate Commands... On Command... Maps to `on`... Off Command... Maps to `off`." MoonHalo's `switch` attribute and `on()`/`off()` commands match the defaults exactly.
  - **Brightness**: "Current Brightness Attribute... Maps to the `level` attribute by default"; "Set Brightness Command... Maps to the `setLevel` command by default." MoonHalo's `level` attribute and `setLevel` command match the defaults exactly.
  - **Color Setting** (quoted in full, README): "NOTE: At least one of 'Full-Spectrum Color Control' and/or 'Color Temperature Control' **must** be set... Color Temperature Control: Set this if the device can have its color temperature set. If set, the following settings become available: Minimum Color Temperature: The minimum color temperature to which the device can be set. Default is 2200. Maximum Color Temperature: ... Default is 6500. Color Temperature Attribute: ... Maps to `colorTemperature` by default. Set Color Temperature Command: A device command used to set the color temperature of the device. Should accept an integer in the range [Minimum Color Temperature, Maximum Color Temperature]. Maps to `setColorTemperature` by default." For MoonHalo: leave "Full-Spectrum Color Control" unchecked, check "Color Temperature Control", set Minimum = 2700 and Maximum = 6500 (the driver's actual range, overriding the 2200/6500 defaults), leave the Color Temperature Attribute and Set Color Temperature Command at their defaults (`colorTemperature`, `setColorTemperature`) since MoonHalo already uses those exact names. Because only Color Temperature Control is set, the "Color Mode Attribute" / "Full-Spectrum Mode Value" / "Color Temperature Mode Value" settings do not appear (those only appear when both controls are set) — confirmed both by the README text and by the code path already documented in `google-home-colour-temperature.md` (`attributesForTrait_ColorSetting` "with 'Full-Spectrum Color Control' off and 'Color Temperature Control' on it emits only `colorTemperatureRange`... No `colorModel`").
- **Assigning devices**: back on the app's main preferences page, a menu item named "{device type name} devices" (i.e., whatever "Device type name" was set to) lists Hubitat devices matching the "Device type" capability filter; check the MoonHalo device there.
- **Report State / Google service account**: **[DOC: source read]**, README "Enabling Google Home Graph Support" section — optional, not required for basic control: "The Google Home Graph API is used for requesting that Google update its list of devices when changes are made and for proactively pushing device events to Google to enable some Google Home features such as device-based automation triggers." Setup requires enabling the Homegraph API, creating a GCP service account, and pasting its JSON key into "Google Service Account Authorization" on the app's main settings page. Without it, Google will still poll device state via `QUERY` on demand; you just lose push-based state updates and the "Push device events to Google" toggle has nothing to push to.

## 5. Testing / publishing requirements

**[DOC]**, `https://developers.home.google.com/cloud-to-cloud/test` (read 2026-09-07, full text retrieved): the current "Test" page in the Developer Console runs the **Test Suite**, which is oriented around **certification** ("Use the Test Suite in the Developer Console to submit test results for certification"). Key points relevant to whether an unpublished/uncertified integration works for personal use:

- Testing does **not** require your own separate project: "You can test an integration that hasn't yet been submitted for certification within the same project you used to develop the integration."
- **[DOC]** on adding other users ("If your integration requires alpha testing..."): "Add the tester as a Viewer/Editor through the Google Cloud project that backs the Cloud-to-cloud integration... Once the tester clicks the Test tab... they will be taken to the Test Suite page with an 'Unlinked action'... Once the previous steps are complete, the integration will be visible in the Google Home app (GHA) for the tester." This implies the **project owner's own Google account** (the developer) does not need this extra IAM step — you already have project access; only *other* people you want to test with (e.g. household members using a different Google account) need to be added as Viewer/Editor in the backing Google Cloud project.
- Nothing in the current docs states a certification/publishing requirement to use your own integration; certification ("Certify" tab, "Submit for certification review") is described as the path to public launch, separate from development/testing use. **[INFERENCE]**: for a single-user, self-hosted integration like this one, certification is never needed — this matches the entire premise of the README (a hobby project with no submitted certification) and years of forum reports of people using it uncertified.
- The **"[test] {name}"** labelling in the Google Home app (README step 23, and confirmed still present as of 2023 by `mbudnek` in GitHub issue #106, https://github.com/mbudnek/google-home-hubitat-community/issues/106: "The old `[test] Hubitat` entries will stay there until Google fixes their bug") was not independently re-confirmed after the December 2024 console migration by any primary source found. **[INFERENCE]**: since the underlying mechanism (an uncertified action shown to its own developer/testers) is unchanged in the current docs, the "[test]" prefix likely persists, but this is inference, not observation.

## 6. Hubitat Package Manager listing

Yes — confirmed via three chained primary sources, not just the README (which does not mention HPM at all: `grep -i "package manager\|HPM" README.md` returns nothing):

1. **[DOC: source read]** HPM's own app source, `https://raw.githubusercontent.com/HubitatCommunity/hubitatpackagemanager/main/apps/Package_Manager.groovy`, line 116: `repositoryListing = "https://raw.githubusercontent.com/HubitatCommunity/hubitat-packagerepositories/master/repositories.json"` — this is HPM's actual default repository-of-repositories, distinct from (and not to be confused with) the `HubitatCommunity/hubitatpackagemanager` repo itself, which is the *app*, not a package list.
2. **[DOC: source read]** That `repositories.json` lists, among many per-author repos: `{"name": "Miles Budnek (@mbudnek)", "location": "https://raw.githubusercontent.com/mbudnek/hubitat-package-manager-repo/master/repository.json"}`.
3. **[DOC: source read]** That per-author `repository.json` lists: `{"name": "Google Home Community", "category": "Integrations", "location": "https://raw.githubusercontent.com/mbudnek/google-home-hubitat-community/master/packageManifest.json", "description": "A community-maintained, full-featured, and highly configurable integration between Hubitat Elevation and Google Home."}`, pointing at the `packageManifest.json` already quoted in Question 2 (`"oauth": true`, `"required": true`).

So the integration is installable through HPM's default "Search by Keywords" / repository browse flow (it does not need a custom/manual repository added), matching community reports: **[FORUM]** `danabw`, https://community.hubitat.com/t/63108/2 (2021-01-27): "There is a Google Home Community app that is more flexible. You can install it from HPM. Search 'Google Home Community' for the release thread." and **[FORUM]** GitHub issue #85 (2022-05-21), https://github.com/mbudnek/google-home-hubitat-community/issues/85, where `mbudnek` explains the HPM install path still requires the manual Apps Code -> OAuth step: "Yeah, HPM has an option to enable OAuth, but actually needing to copy the client ID and secret is unusual enough that it doesn't provide a way to access them" — i.e. HPM will install and can toggle OAuth on, but the Client ID/Secret must still be read from the "OAuth" button in Apps Code (README steps 4–8), not from HPM's UI.

## Summary for the wizard

1. Create a project at `console.home.google.com` (not `console.actions.google.com`).
2. Install the app in Hubitat (Apps Code, paste, enable OAuth, note Client ID/Secret; install via HPM by searching "Google Home Community" works equally, but OAuth must still be enabled/read from Apps Code afterward) and note the app ID from the installed-app URL and the Hub UID from Settings -> Hub Details.
3. In the console: Open project -> "Add cloud-to-cloud integration" -> Next: Develop -> Next: Setup -> on "Setup & configuration": name it, pick a device type (any/all — MoonHalo isn't a certification concern), upload a 144×144 icon, fill "Account linking" (Client ID/Secret from step 2, Authorization URL `https://oauth.cloud.hubitat.com/oauth/authorize`, Token URL `https://oauth.cloud.hubitat.com/oauth/token`, Scope `app`), fill "Cloud fulfillment URL" (`https://cloud.hubitat.com/api/{hubUID}/apps/{appId}/action`) -> Save.
4. In the Hubitat app, define a device type: name it, Device type = "Color Temperature", Google Home device type = "Light", traits On/Off + Brightness + Color Setting (Color Temperature Control only, min 2700 / max 6500), assign the MoonHalo device.
5. Before linking, remove MoonHalo from the built-in Google Home app's device list (leave the rest of that app's devices alone) to avoid a duplicate/conflicting registration.
6. Link in the Google Home mobile app: "+" -> "Set up device" -> "Works with Google" -> find `[test] {integration name}` -> sign in with Hubitat credentials -> select hub -> select MoonHalo -> Authorize.
7. Sync: swipe down in the Google Home app, or "Hey Google, sync my devices".

Two points remain unverified by a primary source and should be treated as "confirm on screen" steps in the wizard rather than scripted blind: the exact current field labels in the console's "Account linking" section, and whether the "[test] {name}" label still appears verbatim post-migration.

## Sources read

- https://raw.githubusercontent.com/mbudnek/google-home-hubitat-community/master/README.md (465 lines, full text)
- https://raw.githubusercontent.com/mbudnek/google-home-hubitat-community/master/google-home-community.groovy (5629 lines; `mappings` block, `HUBITAT_DEVICE_TYPES`, `GOOGLE_DEVICE_TYPES`, `deviceTypePreferences` page)
- https://raw.githubusercontent.com/mbudnek/google-home-hubitat-community/master/packageManifest.json
- https://raw.githubusercontent.com/HubitatCommunity/hubitatpackagemanager/main/apps/Package_Manager.groovy (line 116, default repository list URL)
- https://raw.githubusercontent.com/HubitatCommunity/hubitat-packagerepositories/master/repositories.json
- https://raw.githubusercontent.com/mbudnek/hubitat-package-manager-repo/master/repository.json
- https://developers.home.google.com/cloud-to-cloud/project/create (full text retrieved via curl with a browser User-Agent — server-rendered)
- https://developers.home.google.com/cloud-to-cloud/integration/create (full text retrieved)
- https://developers.home.google.com/cloud-to-cloud/project/migration (full text retrieved)
- https://developers.home.google.com/cloud-to-cloud/primer/account-linking (full text retrieved)
- https://developers.home.google.com/cloud-to-cloud/project/authorization (full text retrieved)
- https://developers.home.google.com/cloud-to-cloud/test (full text retrieved)
- https://developers.home.google.com/cloud-to-cloud/get-started (full text retrieved)
- https://developers.home.google.com/cloud-to-cloud/integration/account-linking — 404, does not exist under that path
- https://docs2.hubitat.com/en/apps/google-home (full text retrieved, server-rendered)
- Several guessed `docs2.hubitat.com/en/developer/...` OAuth/cloud-endpoint paths — all 404, no working URL found, no sitemap.xml
- https://community.hubitat.com/t/34957 (JSON; announcement/support thread, 1205 posts) — posts 6, 9 (2020-02-24/25, multiple-integration coexistence), 1148, 1150, 1160, 1163 (2024, console migration)
- https://community.hubitat.com/t/63108 (JSON; posts 1–4, HPM install mention)
- https://community.hubitat.com/search.json — queries for "Home Developer Console", "console.home.google.com", "cloud-to-cloud" google home, "same time" "google home community", "built-in" google home, "duplicate device", "remove from google home app", "Works with Google Home" #34957 (several returned no results, noted where relevant)
- https://github.com/mbudnek/google-home-hubitat-community/issues/117 (2025-02-23, console migration hit by a user)
- https://github.com/mbudnek/google-home-hubitat-community/issues/110 (2023-06-19, `[test]` app linking failure)
- https://github.com/mbudnek/google-home-hubitat-community/issues/106 (2023-03-08, `[test] Hubitat` entries persist, de-authorizing)
- https://github.com/mbudnek/google-home-hubitat-community/issues/85 (2022-05-21, HPM + OAuth)
- https://github.com/mbudnek/google-home-hubitat-community/issues/47 (2020-11-03, fulfilment URL / duplicate app troubleshooting)
- `gh issue list -R mbudnek/google-home-hubitat-community --search ...` for "Home Developer Console", "console.home.google.com", "cloud-to-cloud", "migrat", "new console", "actions.google.com", "deprecat", "duplicate", "official", "built-in", "at the same time" — all issues found are listed above; searches otherwise returned no additional results
