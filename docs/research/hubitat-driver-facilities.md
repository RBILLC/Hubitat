# Hubitat Driver Facilities — Research Notes

Scope: primary-source research for a driver that makes outbound LAN HTTP calls and presents itself as a
dimmable, colour-temperature-capable light (`Switch` + `SwitchLevel` + `ColorTemperature` + `Light`, likely
also `Refresh`/`Initialize`/`Actuator`).

All facts below are sourced from docs2.hubitat.com (fetched via a live browser render — the site is a
JavaScript SPA, so a plain HTTP fetch only returns the page `<title>`) and from the official
`hubitat/HubitatPublic` GitHub example-drivers repository. Where a claim comes from an example driver rather
than the documentation, this is stated explicitly. Anything not found in the sources consulted is labeled
as such rather than guessed.

---

## 1. `asynchttpGet` and the async-HTTP family

Source: [Common Methods](https://docs2.hubitat.com/en/developer/common-methods-object) (rendered page text).

Exact documented signature:

> `void asynchttpGet(callbackMethod, Map params, Map data = null)`

Parameters, verbatim from the page:

- `callbackMethod` - "The name of a callback method to send the response to. Can be null if the response can be ignored."
- `params` - the parameters to use to build the HTTP GET call. Possible keys: `uri`, `queryString`, `query`, `headers`, `path`, `contentType`, `requestContentType`, and:
  - `timeout` (since 2.0.9) - **"timeout in seconds for the request, max timeout is 300"**. No explicit "default" value is stated anywhere in the fetched page — the docs give only the unit (seconds) and the maximum (300s). **The default timeout value is not documented in the sources consulted.**
  - `ignoreSSLIssues` (since 2.1.8) - true/false, ignore cert issues, defaults to false.
  - `followRedirects` (since 2.2.9) - true/false, defaults to true.
- `data` - "optional data to be passed to the callback method."

The same `timeout`/`ignoreSSLIssues`/`followRedirects` options and the "max timeout is 300" (seconds) ceiling are repeated identically for `asynchttpPost`, `asynchttpPatch`, `httpGet`, `httpPost`, `httpPostJson`, `httpPut`, and `httpPatch` on the same page.

Sibling async methods whose full signatures are documented only in the page's "Additional to be documented" list (names/signatures given, no parameter prose):

```
void asynchttpPut(String callbackMethod = null, Map params, Map data = null)
void asynchttpDelete(String callbackMethod = null, Map params, Map data = null)
void asynchttpHead(String callbackMethod = null, Map params, Map data = null)
```

### Callback naming and invocation

The callback is referenced by **method name as a String** (or bare identifier — Groovy allows omitting quotes for a method reference in this position; the working LAN driver example (`Building a LAN or Cloud Driver`, see below) passes it as a quoted string, `"myCallback"`). The documentation does not show the exact callback method signature on the Common Methods or Driver Object pages, but the **Building a LAN/Cloud Driver** guide gives a worked example:

> ```groovy
> asynchttpPost("myCallback", params)
>
> void myCallback(resp, data) {
>   // Normally you'd also want to check for errors and actually
>   // use the data, but for this example, we'll just log:
>   def json = resp.json
>   log.trace "json = $json"
> }
> ```
Source: [Building a LAN or Cloud Driver](https://docs2.hubitat.com/en/developer/driver/building-a-lan-driver).

So the callback is invoked with two positional parameters: the response object first, then the `data` map (confirming the third `asynchttpGet`/`asynchttpPost` argument **is** passed through to the callback — this is directly demonstrated in the quoted snippet: `params` doesn't include a `data` value in that snippet, but the callback signature `myCallback(resp, data)` and the documented `data = null` parameter of `asynchttpGet`/`asynchttpPost` together establish the pass-through).

### The `AsyncResponse` object (`resp`) — `status`, `hasError()`, `getErrorMessage()`, `getData()`, `getJson()`, `getHeaders()`

**Not documented in the sources consulted.** None of the fetched pages (`Common Methods`, `Driver Object`, `Device Object`, `Event Object`, `Attribute Object`, `Driver Overview`, `Building a LAN or Cloud Driver`) name or describe an `AsyncResponse` class, nor do they enumerate `status`, `hasError()`, `getErrorMessage()`, `getData()`, `getJson()`, or `getHeaders()` as members of the callback's response object. The only field the documentation shows in use is `resp.json` (in the snippet quoted above). A site-restricted search (`site:docs2.hubitat.com hasError OR getErrorMessage OR getWarningMessage`) returned no results, and no page reachable from the Developer Documentation index (`https://docs2.hubitat.com/en/developer`) is dedicated to this object. None of the official example drivers inspected (list in section 9) call `asynchttpGet`/`asynchttpPost` at all, so there is no example-driver usage to fall back on either.

**Consequently, the following are not documented in the sources consulted and should not be assumed:**
- The exact getter names/casing on the response object beyond `.json` (a property-style accessor, not shown as `getJson()`).
- What `status` or error state is reported on a connection timeout.
- What `status` or error state is reported on a refused/reset connection.

## 2. Capability contracts

Source: [Driver Capability List](https://docs2.hubitat.com/en/developer/driver/capability-list) (rendered page text; this is the canonical, complete listing — quoted directly per capability below).

### Switch
```
Driver Definition: capability "Switch"
Attributes: switch - ENUM ["on", "off"]
Commands: off()  on()
```

### SwitchLevel
```
Driver Definition: capability "SwitchLevel"
Attributes: level - NUMBER, unit:%
Commands:
  setLevel(level, duration)
    level required (NUMBER) - Level to set (0 to 100)
    duration optional (NUMBER) - Transition duration in seconds
```
Full documented signature: **`setLevel(level, duration)`** — only two parameters are documented at the capability-contract level (no separate "rate" argument beyond `duration`).

### ColorTemperature
```
Driver Definition: capability "ColorTemperature"
Attributes:
  colorName - STRING
  colorTemperature - NUMBER, unit:°K
Commands:
  setColorTemperature(colortemperature, level, transitionTime)
    colortemperature required (NUMBER) - Color temperature in degrees Kelvin
    level optional (NUMBER) - level to set
    transitionTime optional (NUMBER) - transition time to use in seconds
```
Full documented signature, in order: **`setColorTemperature(colorTemperature, level = optional, transitionTime = optional)`**.

### Light
```
Driver Definition: capability "Light"
Attributes: switch - ENUM ["on", "off"]
Commands: off()  on()
```
(`Light` duplicates the `Switch` contract — same attribute and commands are listed under it on the capability-list page.)

### Refresh
```
Driver Definition: capability "Refresh"
Commands: refresh()
```
(No attributes.)

### Initialize
```
Driver Definition: capability "Initialize"
Commands: initialize() - "this method will run on system start on devices using capability
"Initialize" (one common use is re-establishing telnet, websocket, or similar LAN connections for such devices)"
```
(No attributes.)

### Actuator
```
Driver Definition: capability "Actuator"
Attributes: (none)
Commands: (none)
```
`Actuator` is a marker capability with no required commands or attributes — it exists to make the device eligible for command-driven use in apps/rules (this inference is standard Hubitat usage; the capability-list page itself just shows an empty Attributes/Commands section for it, with no further prose explanation on that page).

### Cross-check against example drivers
The `advancedZigbeeCTbulb.groovy` and `GenericZigbeeRGBWBulb.groovy` examples both implement:
```groovy
List<String> setColorTemperature(colorTemperature, level = null, tt = null) { ... }
```
(`GenericZigbeeRGBWBulb.groovy` line 483; `advancedZigbeeCTbulb.groovy` line 473 — see section 9), which matches the 3-argument, 2-optional-argument order documented in the capability list (`colortemperature, level, transitionTime`), confirming the argument order in a second independent source.

## 3. Scheduling

Source: [Common Methods](https://docs2.hubitat.com/en/developer/common-methods-object), and [Driver Overview](https://docs2.hubitat.com/en/developer/driver/overview) / [Driver Capability List](https://docs2.hubitat.com/en/developer/driver/capability-list) for `Initialize`.

### `runIn`
```
String runIn(Long delayInSeconds, String handlerMethod, Map options = null)   (since 2.4.2)
void   runIn(Long delayInSeconds, String handlerMethod, Map options = null)   (2.4.1 and earlier)
```
`options` map:
- `overwrite` - "defaults to true, which cancels the previous scheduled running of the handler method and schedules new; if set to false, this will create a duplicate schedule."
- `data` - optional Map of data passed to the handler method.
- `misfire` - "If set to "ignore" then the scheduler will simply try to fire it as soon as it can. NOTE: if a scheduler uses this instruction, and it has missed several of its scheduled firings, then several rapid firings may occur..."

Since 2.4.2, `runIn` returns a job-ID string usable with `cancelRunIn(String jobId)` (returns true/false); earlier platform versions return `void`.

Example from the page:
```groovy
runIn(50, "myMethod", [data: [myKey:"myValue"]])
void myMethod(data) {
  log.debug "myMethod parameter: $data"
}
```

### `runEvery*` family
Documented only as bare signatures in the page's "Additional to be documented" list (no prose beyond signature), but the exact method names ARE given verbatim:
```
void runEvery1Minute(String handlerMethod, Map options = null)
void runEvery5Minutes(String handlerMethod, Map options = null)
void runEvery10Minutes(String handlerMethod, Map options = null)
void runEvery15Minutes(String handlerMethod, Map options = null)
void runEvery30Minutes(String handlerMethod, Map options = null)
void runEvery1Hour(String handlerMethod, Map options = null)
void runEvery3Hours(String handlerMethod, Map options = null)
```
No `runEvery2Hours`/`runEvery6Hours`/etc. variants are listed anywhere on the page — only the seven names above are documented. (A `runInMillis` and `runOnce` also exist — see below — but there is no "runEvery" granularity between 30 minutes and 1 hour, nor between 1 and 3 hours, in the sources consulted.)

### `runInMillis`
```
void runInMillis(Long delayInMilliSeconds, String handlerMethod, Map options = null)
```
Same `options` shape (`overwrite`, `data`, `misfire`) as `runIn`.

### `runOnce`
```
String runOnce(Date dateTime, String handlerMethod, Map options = null)     (since 2.4.2)
String runOnce(String dateTime, String handlerMethod, Map options = null)   (since 2.4.2)
void   runOnce(Date dateTime, String handlerMethod, Map options = null)     (2.4.1 and earlier)
void   runOnce(String dateTime, String handlerMethod, Map options = null)   (2.4.1 and earlier)
```
Returns a job ID usable with `cancelRunOnce(String jobId)` since 2.4.2.

### `schedule` (cron)
```
void schedule(String expression, String handlerMethod, Map options = null)
void schedule(Date dateTime, String handlerMethod, Map options = null)   -- listed only in "Additional to be documented"
```
> "expression - a 7-parameter Quartz cron string where the expression is: 'Seconds' 'Minutes' 'Hours' 'Day Of Month' 'Month' 'Day Of Week' 'Year'"

Example: `schedule("0 */10 * ? * *", "mymethod")` — run every 10th minute. `options` supports `overwrite` and `data`, same semantics as `runIn`.

### `unschedule`
```
void unschedule()                    // removes all scheduled tasks for this driver/app instance
void unschedule(handlerMethod)       // removes only schedules for this handlerMethod
```

### When `Initialize`'s `initialize()` is called
Per the Driver Capability List page (quoted above): `initialize()` **"will run on system start on devices using capability 'Initialize'"** — i.e., hub restart/boot, not on every driver save. The Driver Overview page separately confirms, in its list of lifecycle methods: **"initialize(): called on hub startup if driver specifies capability 'Initialize' (otherwise is not required or automatically called if present)."** So `initialize()` is *not* documented to run on a driver code save/`updated()` cycle — only on hub startup. Whether it is also invoked after a driver is newly installed (as opposed to only on a subsequent hub reboot) is **not documented in the sources consulted**.

The `thirdRealityMatterNightLight.groovy` example driver (Matter, not LAN-HTTP) implements this capability and uses `initialize()` to re-subscribe to the device on startup:
```groovy
capability "Initialize"
// ...
void initialize() {
    sendToDevice(subscribeCmd())
}
```
(https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/thirdRealityMatterNightLight.groovy, lines 47 and 260-262) — this illustrates the documented "re-establishing ... LAN connections" use case even though this particular example is Matter rather than LAN/HTTP.

## 4. Custom commands with typed parameters, custom attributes

Source: [Device Definition](https://docs2.hubitat.com/en/developer/driver/definition).

### Custom commands
```
command "commandName"
command "commandName", parameters
```
Simple form — a list of bare type names, no validation performed:
```groovy
command "myCommand", ["number", "string"]
```
Expanded form — each parameter is a Map:
> "type - The type of the parameter, which can be any of STRING, NUMBER, DATE, ENUM, JSON_OBJECT, or COLOR_MAP. Note that a driver can only have a single command that accepts a COLOR_MAP."

Other map keys: `name` (display name; "If the name ends with an asterisk (*), the parameter is considered required"), `description` (tooltip text), `constraints` ("A list of the valid options for an ENUM").

Expanded example, quoted verbatim:
```groovy
command "myCommand", [
    [name:"My first parameter*", type:"STRING", description:"Description of this required string parameter"],
    [name:"Color", type: "ENUM", description: "Description of this second parameter", constraints: ["red","blue","green"]]
]
```
So **ENUM constraints are declared via the `constraints` key as a List of allowed String values**, and a parameter is marked required purely by appending `*` to its display `name` — there is no separate `required: true` key at the command-parameter level (contrast with `input`, which does use a `required` key — see section 5).

The allowed parameter **types** for custom commands are exactly: `STRING`, `NUMBER`, `DATE`, `ENUM`, `JSON_OBJECT`, `COLOR_MAP`.

### Custom attributes
```
attribute "attributeName", type              // type must be one of: string, number, enum (etc.)
attribute "enumAttribute", "enum", values    // values = Groovy list of allowed enum values
```
Example:
```groovy
attribute "myAttribute", "string"
attribute "enumAttribute", "enum", ["value 1", "value 2"]
```
The page also cross-references the [Attribute Object](https://docs2.hubitat.com/en/developer/attribute-object) page, which documents the underlying `dataType` values more fully: `ENUM`, `STRING`, `DYNAMIC_ENUM` ("not currently differentiated from other String values (not recommended for use)"), `JSON_OBJECT`, `NUMBER`, `DATE` ("not currently standardized"), `VECTOR3` ("not currently standardized, but a format like "[x:1,y:2,z:3]" is conventional").

### Example-driver usage
`advancedZigbeeCTbulb.groovy` declares a typed custom command:
```groovy
command "presetLevel", [[name:"Preset Level*", type:"NUMBER", description:"Preset a level (1..100)", constraints:["NUMBER"]]]
```
(line 91) — note this example puts `"NUMBER"` in `constraints` even though `constraints` is documented as being for ENUM values specifically; this is the example driver's own (arguably non-canonical) usage, not something the docs prescribe.

`virtualActuator.groovy` declares a bare custom attribute with no explicit type/value list:
```groovy
attribute "switchPosition", "ENUM"
```
(line 15) — this omits the enum `values` list that the Device Definition page's syntax shows as part of the `attribute "name", "enum", values` form; again, this is what the example does, not what the docs prescribe as the complete/correct form.

## 5. Preferences (`input`)

Source: [Device Preferences](https://docs2.hubitat.com/en/developer/driver/preferences) and [Driver Overview](https://docs2.hubitat.com/en/developer/driver/overview).

Structure:
```groovy
metadata {
    preferences {
        input name: "settingName", type: "text", title: "My Setting", description: "Enter Setting Text", required: true
    }
}
```

Documented `input` keys (Device Preferences page):
- `name` - "Uniquely identifies this setting"
- `type` - **"bool, date, decimal, email, enum, number, password, time, text"** (verbatim list from the Device Preferences page — a superset of the types given on the Driver Overview page)
- `title` - text shown in the driver UI
- `description` - optional long description
- `required` - true/false, "requires a value before the UI allows saving"
- `defaultValue` - default value shown in UI
- `options` - "Only available when the type is enum. Allows you to specify the values that appear in the dropdown."
- `range` - "Only available when the type is number or decimal. Specify a String in the format 'low..high' ... e.g., '0..10'."

The Driver Overview page gives a second, slightly differently-worded pass over the input types, useful for the type->Groovy-type mapping and enum details:
> "text: String / number: Integer / decimal: Double / enum: List (this type requires a parameter options of type List with the options); this displays as a drop-down menu allowing the selection of a single value that is ultimately saved as a string / bool: Boolean; this is an on/off slider."
> "The options of an enum can be a List of Maps, where the key of the map element is returned while the String value is displayed in the pull-down menu."
> "A defaultValue: value can be specified for an input, which will display in the UI on load but will not be saved to the corresponding setting until the preferences are saved."

### Reading `settings` inside the driver
Per Driver Overview: **"Each input creates a setting with the name specified in the input. These can be accessed in the app directly with the name, e.g., `myName` (as if it were a field/variable name), or with `settings["myName"]`. The `settings` object is a Map with key being the input name, and value being the input value from the user."**

Example-driver usage confirming this: `httpGetSwitch.groovy` reads `settings.onURI` / `settings.offURI` directly (lines 39, 42, 55, 58), and also reads `onURI`/`offURI` bare-name style is implied but not actually used in that file — it consistently uses `settings.xxx`.

## 6. `sendEvent` and `device.currentValue`

Source: [Driver Object](https://docs2.hubitat.com/en/developer/driver/driver-object), [Device Object](https://docs2.hubitat.com/en/developer/device-object), [Event Object](https://docs2.hubitat.com/en/developer/event-object).

### `sendEvent`
```
void sendEvent(Map properties)
```
Documented keys on the Driver Object page:
- `name` (String, required) - "name of the event (normally the [sic] name of a device attribute)"
- `value` (required) - "value of the event (data type should match the type defined for the attribute as defined by either the capability or custom attribute type)"
- `unit` (String) - "units corresponding to the value (e.g., could be '%' for level or omitted for switch)"
- `descriptionText` (String) - "a human-friendly description of the event ... e.g., 'Living Room Dimmer level is 50%' or 'Bedroom Button pushed is 1 [physical]'"
- `isStateChange` (Boolean) - "set to true to force an event to be generated even if the new value is the same as the old value (optional and usually omitted in favor of default filtering by platform; button events are one case where it is often needed)"

Example from the page: `sendEvent(name: "colorTemperature", value: 2700, unit: "K")`.

The **`type`** key is *not* listed among `sendEvent`'s documented parameters on the Driver Object page. It is, however, documented as a **property of the resulting Event object** on the [Event Object](https://docs2.hubitat.com/en/developer/event-object) page:
> "type - String - May be 'physical' (if event was generated by user action on the device itself, e.g., pressing a button/switch) or 'digital' (if generated as a result of a command sent from the hub), or null (default and very common)"
This implies `type` can be passed into `sendEvent(...)` (it appears as a settable Event property elsewhere in Hubitat driver conventions), but **the Driver Object page's own parameter list for `sendEvent` does not include `type`**, so its acceptance as a `sendEvent` argument is not directly confirmed in the primary sources fetched here — treat this as likely-but-not-textually-confirmed.

There is also `createEvent(Map options)` (same options as `sendEvent`), which builds an event Map without firing it; it must be returned from `parse()` to take effect. Hubitat's own guidance: **"Alternatively, use sendEvent() to create and fire an event (our recommendation). These methods are otherwise identical."**

### `device.currentValue`
Source: [Device Object](https://docs2.hubitat.com/en/developer/device-object).
```
Object currentValue(String attributeName)
Object currentValue(String attributeName, boolean skipCache)
```
> "skipCache - Optional; defaults to false. If true, do not use the cached value of the attribute (values are cached during a single execution of the driver); instead force the system to read the latest from the database."

## 7. `state` and `device.updateSetting`

Source: [Driver Overview](https://docs2.hubitat.com/en/developer/driver/overview), [Device Object](https://docs2.hubitat.com/en/developer/device-object), [Best Practices](https://docs2.hubitat.com/en/developer/best-practices).

`state` is described as: **"a built-in state object available. This object behaves like a Map and allows storing most common data types (strings, numbers, Lists or Maps of such objects, etc. — anything that can be serialized to/from JSON). Each device has its own state object."** Example: `state.foo = "bar"`.

`atomicState` is the same data store but commits immediately rather than at the end of driver execution: **"state writes data just before the driver goes to sleep again, whereas atomicState commits the changes as soon as they are made. We suggest beginning with state and changing to atomicState only if there are concerns for simultaneous execution ... Use of state is more efficient."** A convenience method exists: `atomicState.updateMapValue(Object stateKey, Object key, Object value)`.

Best Practices page adds an efficiency-vs-state-vs-attribute framing (see section 8) and notes `state`/`atomicState` values "are not persisted across a hub reboot or re-save of app or driver code" when talking about the *alternative* static-field/File-Manager storage options — that specific non-persistence caveat is stated about `@Field` statics and File Manager files, not about `state` itself (state/atomicState ARE persisted across reboots per the driver-overview description of them as the persistent store "between executions").

### `device.updateSetting`
Source: [Device Object](https://docs2.hubitat.com/en/developer/device-object).
```
void updateSetting(String name, Map options)      // options = [type: ..., value: ...], e.g. [type: "number", value: 5]
void updateSetting(String name, Long value)
void updateSetting(String name, Boolean value)
void updateSetting(String name, String value)
void updateSetting(String name, Double value)
void updateSetting(String name, Date value)
void updateSetting(String name, List value)
```
> "Updates the value of a setting (preference) to the specified value. If the setting does not exist, this method will create it."

Example-driver usage, `httpGetSwitch.groovy`:
```groovy
device.updateSetting("logEnable", [value: "false", type: "bool"])
```
(line 25) and `genericComponentDimmer.groovy` / `componentSwitch.groovy`:
```groovy
device.updateSetting("txtEnable",[type:"bool",value:true])
```
— both confirm the `[type:, value:]` Map form is what's actually used in practice, and that the key order (`type` vs `value` first) doesn't matter.

## 8. Not blocking the hub: sync vs. async HTTP, timeouts, log levels

### Sync vs. async guidance
Source: [Building a LAN or Cloud Driver](https://docs2.hubitat.com/en/developer/driver/building-a-lan-driver).
> "Synchronous or asynchronous HTTP GET, PUT, or POST actions can be done using methods such as httpGet() or asynchttpGet() as described in Common Methods. **The async methods are recommended whenever possible.**"

This is the only explicit statement found across the fetched pages about preferring async HTTP. No fetched page explicitly says *why* (e.g., no page states that synchronous `httpGet`/`httpPost` block the single execution thread for the driver/app, though that is the well-known practical implication of "the async methods are recommended"). **The specific mechanism/consequence of hub-blocking from synchronous HTTP calls is not spelled out in the sources consulted** — only the recommendation itself is stated.

### Timeouts
As in section 1: `timeout` on `httpGet`/`httpPost`/`httpPut`/`httpPatch`/`httpPostJson` and all `asynchttp*` variants is in **seconds**, available "since 2.0.9", with a stated **maximum of 300** seconds. No default value is given anywhere in the fetched Common Methods page.

### Log levels
Source: [App Overview](https://docs2.hubitat.com/en/developer/app/overview) (explicitly stated to apply equally to drivers — the Driver Overview page says: **"Logging methods availalbe are the same as those for apps."**).
> "Available methods are: log.info / log.debug / log.trace / log.warn / log.error"
> "These will tag the log entry in Logs with the specified 'level,' e.g., a white 'info' box next to the log entry, a blue 'debug' box or a red 'error' box. Info and debug logs are the most commonly used type across apps and drivers."

So there are **five** documented log methods — `info`, `debug`, `trace`, `warn`, `error` — not just the four the research ticket names (`debug/info/warn/error`); `trace` is also documented and used in the official "simple app"/driver examples (e.g., `log.trace "installed()"`).

The [Best Practices](https://docs2.hubitat.com/en/developer/best-practices) page adds: **"Writing log entries, in general, has little chance of affecting hub performance. However, many users prefer to control if or how apps and drivers create log entries and for what types of information."** — this is the closest thing to logging-level guidance found, and it is about user preference/configurability (hence the common community pattern, also seen in the example drivers, of a `logEnable` boolean preference plus a `runIn(1800, logsOff)` auto-disable — see `httpGetSwitch.groovy` and `advancedZigbeeCTbulb.groovy` `updated()` methods), not about hub performance cost of any specific log level.

## 9. Idiomatic LAN/HTTP driver structure (from example drivers)

Repository listing (`gh api repos/hubitat/HubitatPublic/contents/examples/drivers`) as of this research:
`GenericZigbeeRGBWBulb.groovy, LifxColorBulbLegacy.groovy, advancedZigbeeCTbulb.groovy, basicZWaveTool.groovy, componentSwitch.groovy, environmentSensor.groovy, genericComponentDimmer.groovy, genericComponentParentDemo.groovy, genericZWaveCentralSceneDimmer.groovy, haloSmokeCoDetector.groovy, httpGetSwitch.groovy, irisKeypadV3.groovy, kasaPlugHubRebooter.groovy, neeoRemote.groovy, ringKeypadG2.groovy, sofabatonX1S.groovy, thirdRealityMatterNightLight.groovy, virtualActuator.groovy, virtualLock.groovy, virtualOmniSensor.groovy, virtualOpenVentArea.groovy, virtualRGBW.groovy, virtualThermostat.groovy`

**Note:** none of these 23 files is a HTTP-async example; the one clearly LAN/HTTP-oriented driver is `httpGetSwitch.groovy`, and it uses **synchronous** `httpGet`, not `asynchttpGet`. `kasaPlugHubRebooter.groovy` uses synchronous `httpPost` similarly. No official example in this repository demonstrates `asynchttpGet`/`asynchttpPost` or the `AsyncResponse` object — this is a real gap between "recommended practice" (section 8) and "what the official examples show."

### `httpGetSwitch.groovy` — the canonical LAN HTTP example
URL: https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/httpGetSwitch.groovy

Full URI is stored directly as a user preference (`onURI`, `offURI` text inputs), not built up from a host/path — there is no `uri`/`path` param-Map construction in this driver, e.g.:
```groovy
preferences {
    input "onURI", "text", title: "On URI", required: false
    input "offURI", "text", title: "Off URI", required: false
    input name: "logEnable", type: "bool", title: "Enable debug logging", defaultValue: true
}

def on() {
    if (logEnable) log.debug "Sending on GET request to [${settings.onURI}]"
    try {
        httpGet(settings.onURI) { resp ->
            if (resp.success) {
                sendEvent(name: "switch", value: "on", isStateChange: true)
            }
            if (logEnable)
                if (resp.data) log.debug "${resp.data}"
        }
    } catch (Exception e) {
        log.warn "Call to on failed: ${e.message}"
    }
}
```
Error handling pattern: wrap the synchronous `httpGet` call in `try { ... } catch (Exception e) { log.warn "..." }`; success is checked via `resp.success` inside the closure before firing the event — i.e. the event is only sent on success, and no event/no error attribute is set on failure beyond the warn log.

Lifecycle in this driver: only `updated()` (schedules a debug-log auto-off via `runIn(1800, logsOff)`) and `parse(String description)` (just logs, since it's not really receiving unsolicited LAN traffic in a meaningful way here) — there is **no `installed()` or `configure()`** in this particular example.

### `advancedZigbeeCTbulb.groovy` — CT-bulb lifecycle idiom (not LAN, but shows the `installed`/`updated`/`configure` split relevant to a CT light driver)
URL: https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/advancedZigbeeCTbulb.groovy
```groovy
List<String> configure() {
    log.warn "configure..."
    runIn(3,runOptionTest)
    return configAttributeReporting()
}

List<String> updated(){
    log.info "updated..."
    log.warn "debug logging is: ${logEnable == true}"
    log.warn "description logging is: ${txtEnable == true}"
    if (logEnable) runIn(1800,logsOff)
    return configAttributeReporting()
}
```
Both `configure()` and `updated()` **return a `List<String>`** of protocol command strings — this is the general Hubitat idiom (documented on [Driver Object](https://docs2.hubitat.com/en/developer/driver/driver-object) under `response()`/`HubAction` as "Additional to be documented", not spelled out in prose on the fetched pages, but directly demonstrated here and consistent with Driver Overview's note that on() as a command method is expected to talk to the device): a command method builds a list of outgoing protocol commands and returns them, and the platform sends them. No `installed()` method is present in this file at all (a possible gap/omission in this particular example, not something the docs require).

### `genericComponentDimmer.groovy` — dimmer example, parent/child idiom
URL: https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/genericComponentDimmer.groovy
```groovy
capability "Light"
capability "Switch"
capability "Switch Level"
capability "ChangeLevel"
capability "Refresh"
capability "Actuator"
...
void setLevel(level) {
    parent?.componentSetLevel(this.device,level)
}
void setLevel(level, ramp) {
    parent?.componentSetLevel(this.device,level,ramp)
}
```
This is a **component driver** (delegates every command to `parent?.componentXxx(this.device, ...)`), which is a different architecture than a standalone LAN driver — it is included here only to show the two documented `setLevel` overload shapes (`setLevel(level)` / `setLevel(level, ramp)`) as actually implemented, which matches the capability-list's `setLevel(level, duration)` (the second parameter is just named `ramp` instead of `duration` in this file — the docs use `duration`, examples are free to name the Groovy parameter differently since names aren't part of the wire contract).

### `virtualRGBW.groovy` — virtual CT/RGBW example, `colorName`/`colorMode` convention
URL: https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/virtualRGBW.groovy
```groovy
def setColorTemperature(value, level = null, tt = null) {
    if (value == null) return
    if (level) setLevel(level, tt)
    Integer ct = limitIntegerRange(value,2000,6000)
    if (device.currentValue("switch") != "on") on()
    if (device.currentValue("colorMode") != "CT") {
        eventSend("colorMode","is","CT")
    }
    String verb = (device.currentValue("colorTemperature") == ct) ? "is" : "was set to"
    eventSend("colorTemperature",verb,ct,"°K")
    setGenericTempName(ct)
}
```
This example demonstrates (not documented, but shown in code):
- Clamping the CT value into a fixed range (`limitIntegerRange(value,2000,6000)`) before storing it.
- Turning the device on as a side effect of `setColorTemperature`/`setColor`/`setHue`/`setSaturation` if it's currently off.
- Setting `colorMode` to `"CT"` (vs `"RGB"`) as its own attribute event whenever a CT command is used — matching the `ColorMode` capability's documented `colorMode - ENUM ["CT", "RGB", "EFFECTS"]` attribute (section 2/capability list).
- Deriving a human-readable `colorName` from the numeric colour temperature via a manually maintained lookup table (`setGenericTempName`), rather than any built-in helper — but see section 10, since Hubitat *does* provide a built-in helper for exactly this that this particular (older, 2018-2022 copyright) example does not use.
- Suppressing duplicate "was set to" wording when the new value equals the current value (`verb = (...) ? "is" : "was set to"`) — a form of de-duplication convention in the description text, though it still **calls `sendEvent` every time** rather than skipping the event — i.e. this is textual de-duplication of the description string, not event de-duplication.

## 10. Other relevant guidance for an outbound-LAN-HTTP, dimmable-CT-light driver

- **`importUrl`** (Device Definition / Driver Overview, optional `definition()` parameter): **"The URL where the Groovy code for this driver can be found (will auto-populate URL field when user selects Import button on driver code page)."** Used in the `httpGetSwitch.groovy` example: `importUrl: "https://raw.githubusercontent.com/hubitat/HubitatPublic/master/examples/drivers/httpGetSwitch.groovy"`.

- **`singleThreaded`** (Device Definition / Driver Overview, optional `definition()` parameter, default `false`): **"If true ..., simultaneous execution of a particular driver instance is prevented. The hub will load driver data (including state), run the called method, and save the data (including state) completely before moving on to any additional calls that may have been queued in the meantime. This applies to 'top level' methods only."** A community forum link is given for more detail (not itself a primary doc source fetched here): https://community.hubitat.com/t/2-2-9-singlethreaded-option-for-apps-drivers/80969. This is also presented in Best Practices as an alternative to `atomicState` for concurrency safety.

- **Event de-duplication**: The only documented de-duplication rule found is on `sendEvent`'s `isStateChange` parameter: **"set to true to force an event to be generated even if the new value is the same as the old value (optional and usually omitted in favor of default filtering by platform)"** — i.e., **by default the platform filters out/suppresses events whose new value equals the currently cached value**, and `isStateChange: true` is the documented override. No page gives further detail on exactly how "same value" is compared (e.g., type coercion/string vs. numeric equality) — **not documented in the sources consulted**.

- **`colorName` conventions**: Hubitat provides **built-in helper methods** for this (documented on [Common Methods](https://docs2.hubitat.com/en/developer/common-methods-object)), which the `virtualRGBW.groovy` example (an older file) does not use, instead reimplementing its own lookup tables:
  ```
  convertTemperatureToGenericColorName(Integer colorTemp)   -- since 2.3.2
    "Converts the given color temperature to a string name. Most commonly used to populate colorName
    attribute in driver." Returns e.g. "Soft White".
  convertHueToGenericColorName(Integer hue, Integer saturation)   -- since 2.3.2
    "Converts the given color (hue and saturation) to a string name ... e.g., "Red", "Spring", "Cyan""
  ```
  A driver built today for a dimmable CT light should prefer `convertTemperatureToGenericColorName()` over hand-rolled lookup tables like the one in `virtualRGBW.groovy`, since it's the documented, versioned, built-in mechanism.

- **`ColorMode` capability**: not explicitly requested in the ticket's capability list, but directly relevant to a CT bulb: `capability "ColorMode"` provides a `colorMode` attribute, `ENUM ["CT", "RGB", "EFFECTS"]`, with no required commands (source: Driver Capability List). `virtualRGBW.groovy` sets this attribute manually alongside `colorTemperature`/`colorName` (see section 9) even though nothing in the docs states this is mandatory for `ColorTemperature`-only drivers — it appears to be convention rather than a hard requirement when a driver additionally declares `capability "ColorMode"`.

- **Sandbox restrictions relevant to an HTTP-calling driver** (Developer Overview): drivers **cannot** "define your own classes or use custom JARs," cannot "use methods like `println()` or `sleep()`," and cannot "create threads" — meaning any "wait" behavior around HTTP calls must go through `pauseExecution(Long millisecs)` (documented on Common Methods) or the scheduler (`runIn`, etc.), not raw `sleep()` or manual threading. Only a "reasonable subset" of Java/Groovy classes may be imported (see [Allowed Classes for Import], linked from the Developer Documentation index but not itself fetched in this research pass).

- **`parseLanMessage()`**: mentioned in Building a LAN or Cloud Driver / Device Code as the method used to decode raw incoming LAN data delivered to `parse()` (e.g., via the documented **port 39501** mechanism: **"Incoming traffic to port 39501 on the hub will be routed to a device with a DNI matching the IP address or MAC address of the source device ... This incoming traffic will be sent to the parse() method in the driver."**). Relevant if the driver needs to receive unsolicited pushes from the LAN device rather than only polling it.

- **Mappings/OAuth HTTP endpoints** are an **app-only** feature, not available to a driver alone: **"While not possible in a driver alone, apps can be configured to handle incoming HTTP traffic ... by defining mappings in the app code."** (Building a LAN or Cloud Driver.) So a pure driver cannot expose its own inbound HTTP endpoint; it can only make outbound calls or receive unsolicited traffic via port 39501/`parse()`.

---

## Open questions

The following were not resolved by the sources listed at the top of this document and would need either a deeper crawl of docs2.hubitat.com, the Hubitat Community forum, or direct experimentation on a hub:

1. **`AsyncResponse` object contract** — no primary-source page documents `status`, `hasError()`, `getErrorMessage()`, `getData()`, `getJson()`, or `getHeaders()` as members of the async callback's response object. Only `.json` is shown, in one snippet.
2. **Status/error reported on a connection timeout vs. a refused/reset connection** for `asynchttpGet` — not documented anywhere found.
3. **Default value of the `timeout` parameter** for `httpGet`/`asynchttpGet`/etc. — only the unit (seconds) and maximum (300) are documented; no default is stated.
4. Whether the third `data` argument's pass-through to the callback is stated in explicit prose anywhere (it is only inferable from the `asynchttpPost` signature plus the `myCallback(resp, data)` example — no page says in words "the data map is passed as the callback's second argument").
5. Whether `sendEvent`'s `type` key (`"physical"`/`"digital"`) is actually an accepted `sendEvent()` **input** parameter, or only ever an attribute of the resulting Event object as read back by subscribers — the Driver Object page's `sendEvent` parameter list does not mention `type` at all.
6. Exact equality/coercion rule the platform uses when deciding whether a new event "represents a change in value" for its default de-duplication filtering (numeric vs. string comparison, etc.).
7. Whether `initialize()` (capability `Initialize`) also fires once immediately after a brand-new device is created/installed, or strictly only on subsequent hub (re)starts.
8. No official example driver in `HubitatPublic/examples/drivers` demonstrates `asynchttpGet`/`asynchttpPost` in practice — so there is no primary-source example of real-world error handling, timeout handling, or callback structure around the async HTTP methods; everything in section 1 beyond the bare signature comes from the one worked snippet in "Building a LAN or Cloud Driver."
9. The exact mechanism/consequence of the hub being "blocked" by synchronous HTTP calls (thread model, timeouts affecting other drivers, etc.) is asserted only indirectly via the "async methods are recommended whenever possible" sentence — no page explains the underlying reason.
10. Whether `capability "ColorMode"` is expected/required alongside `capability "ColorTemperature"` for a well-behaved CT-only (non-RGB) light, or is purely optional — the capability list treats them as fully independent capabilities with no documented interdependency.
