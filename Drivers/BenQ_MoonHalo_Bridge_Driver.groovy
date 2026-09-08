/**
 * BenQ MoonHalo Bridge
 *
 * Presents the MoonHalo backlight of a BenQ RD280UG monitor to the Hub as a
 * dimmable colour-temperature light. The Driver never talks to the monitor:
 * every command is one short asynchronous HTTP GET to the Bridge, the service
 * on the Windows PC the monitor is attached to, using its JSON contract:
 * /moonhalo/on[?level=1-100], /moonhalo/off, /moonhalo/brightness/<0-100>
 * (0 = off), /moonhalo/colortemp/<value>[?stage=1] (1-7 is a hardware step,
 * 1000 or more is Kelvin) and /moonhalo/status; the first four also take
 * transition=<seconds> or sweep=<seconds>. Each reply is
 * {"ok": true, "state": {power, level, brightnessStep, colorTemperature,
 * colorTempStep, monitor}} or {"ok": false, "error": "..."}.
 *
 * Author: RBILLC
 * Import URL: https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy
 *
 * Behaviour:
 * - connectionState goes offline when the Bridge cannot be reached, like a
 *   bulb with no power; switch and level keep their last known values.
 * - Attribute events are emitted only after the Bridge confirms a request,
 *   from the state carried in its reply. Nothing is assumed optimistically.
 * - The Transition (setLevel's rate, setColorTemperature's tt) is forwarded
 *   to the Bridge as the transition query parameter, in seconds: 0 makes the
 *   change immediate. Without a rate, the Default transition preference goes
 *   as the sweep query parameter; blank leaves the Bridge default in place.
 * - on() only asks the Bridge to turn on; the Bridge restores the level it
 *   remembers (or its configured default). The Driver keeps no copy of that
 *   level: Hubitat's Google Home app sends setLevel and then on() for one
 *   slider move, and a Driver-side copy replayed the old level over the new.
 * - setColorTemperature while off turns the MoonHalo on, unless colour
 *   pre-staging is enabled, in which case the colour is stored for later.
 * - No hardware knowledge lives here: no VCP registers, no step maths. The
 *   only hardware-shaped value is the 1-7 step passed through by
 *   setColorTempStep.
 * - The Bridge announces its own LAN address through the Maker API by calling
 *   setBridgeAddress(ip, port) at startup and then every minute. The announced
 *   address is used in preference to the typed Bridge IP, which only matters
 *   until the first announcement arrives. Once an announcement has arrived, a
 *   once-a-minute check marks the Bridge offline when nothing has been heard
 *   from it (no announcement and no reply) for longer than the announcement
 *   timeout. Changing the typed IP or port forgets the announced address
 *   until the next announcement; saving other preferences keeps it.
 *
 * Version: 0.0.10 (pre-release; 1.0.0 on public announcement). The Bridge is versioned separately
 * and only moves when it changes; /health reports its number.
 *
 * Changelog:
 * 2026-09-08 0.0.10 - Default transition (seconds) preference, sent as the sweep query parameter
 *                     when a command carries no rate (issue #37)
 * 2026-09-08 0.0.9 - setLevel's rate and setColorTemperature's tt are forwarded to the Bridge as
 *                    the transition query parameter (seconds; 0 snaps immediately) instead of being
 *                    ignored; a non-numeric or missing value still leaves the Bridge default in
 *                    place (issue #36)
 * 2026-09-07 0.0.8 - setBridgeAddress(ip, port) command and bridgeAddress attribute: the Bridge
 *                    announces its LAN address through the Maker API, the Driver prefers it over
 *                    the typed IP, and a missed announcement marks the Bridge offline (issue #23)
 * 2026-09-07 0.0.7 - on() sends /moonhalo/on and lets the Bridge restore its remembered level;
 *                    the Driver's own lastLevel copy is gone. Google Home sends setLevel then
 *                    on() for one slider move, and on() replayed the stale level (issue #21)
 * 2026-09-04 0.0.6 - connectionState is an attribute again (accepted by Google Home in 0.0.2);
 *                    no ColorMode: Hubitat's built-in Google Home app rejects colorMode without
 *                    full colour and gives a CT-only driver no temperature trait (issue #21)
 * 2026-09-04 0.0.5 - Google Home typing test: colorMode "CT" back, still no custom attribute;
 *                    0.0.4 was accepted but typed as a plain dimmer (issue #21)
 * 2026-09-04 0.0.4 - Google Home typing test: attribute set reduced to the CT bulb's (switch,
 *                    level, colorTemperature, colorName); connectionState kept as a data value;
 *                    stale colorMode/connectionState attributes purged on save (issue #21)
 * 2026-09-04 0.0.3 - Restore ColorMode (colorMode "CT"): without it Google Home typed the device
 *                    as a plain dimmer with no colour-temperature control; Initialize stays out
 *                    (issue #21)
 * 2026-09-04 0.0.2 - Drop ColorMode and Initialize capabilities: still rejected by Hubitat's
 *                    Google Home app with Bulb alone; accepted CT-only drivers declare neither
 *                    (issue #21)
 * 2026-09-04 0.0.1 - Declare Bulb instead of Light: Hubitat's Google Home app rejected the
 *                    device ("not supported by Google Home"); its own CT-only example driver and
 *                    docs use Bulb (issue #21)
 * 2026-09-04 0.0.0 - Initial pre-release (issue #19)
 */

metadata {
    definition (name: "BenQ MoonHalo Bridge", namespace: "rbillc", author: "RBILLC", importUrl: "https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy") {
        capability "Actuator"
        capability "Switch"
        capability "SwitchLevel"
        capability "ColorTemperature"
        capability "Bulb"
        capability "Refresh"


        attribute "connectionState", "enum", ["unknown", "online", "offline"]
        attribute "bridgeAddress", "string"

        command "setColorTempStep", [[name: "Step*", type: "NUMBER", description: "Hardware colour temperature step, 1 (warm) to 7 (cool)"]]
        command "setBridgeAddress", [
            [name: "IP address*", type: "STRING", description: "IPv4 address the Bridge is listening on; sent by the Bridge itself through the Maker API"],
            [name: "Port*", type: "NUMBER", description: "TCP port the Bridge is listening on, 1-65535"]
        ]
    }

    preferences {
        input name: "bridgeIp", type: "text", title: "Bridge IP address (initial)", description: "IPv4 address of the PC running the MoonHalo Bridge; used only until the Bridge announces its own address", required: true
        input name: "bridgePort", type: "number", title: "Bridge port (initial)", defaultValue: 5000, range: "1..65535"
        input name: "announceTimeoutSec", type: "number", title: "Announcement timeout (seconds)", description: "Once the Bridge has announced its address, mark it offline when nothing has been heard from it for this long; 0 disables the check. Must exceed the Bridge's announce_seconds", defaultValue: 200, range: "0..86400"
        input name: "timeoutSec", type: "number", title: "Request timeout (seconds)", defaultValue: 5, range: "1..30"
        input name: "pollMinutes", type: "enum", title: "Poll interval", description: "How often the Hub asks the Bridge for its status", options: [["0": "Disabled"], ["1": "1 minute"], ["5": "5 minutes"], ["10": "10 minutes"], ["15": "15 minutes"], ["30": "30 minutes"]], defaultValue: "5"
        input name: "ctMinKelvin", type: "number", title: "Warm colour temperature (Kelvin)", defaultValue: 2700, range: "1000..20000"
        input name: "ctMaxKelvin", type: "number", title: "Cool colour temperature (Kelvin)", defaultValue: 6500, range: "1000..20000"
        input name: "colorStaging", type: "bool", title: "Enable color pre-staging", description: "Store a colour temperature while the MoonHalo stays off", defaultValue: false
        input name: "defaultTransitionSec", type: "decimal", title: "Default transition (seconds)", description: "Time a full brightness sweep takes when a command carries no rate (0-60; 0 snaps); blank uses the Bridge default", range: "0..60"
        input name: "logEnable", type: "bool", title: "Enable debug logging", defaultValue: true
        input name: "txtEnable", type: "bool", title: "Enable descriptionText logging", defaultValue: true
    }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

void installed() {
    log.info "installed..."
    sendEvent(name: "connectionState", value: "unknown", descriptionText: "${device.displayName} connectionState is unknown")
    initialize()
}

void updated() {
    log.info "updated..."
    log.warn "Bridge IP is: ${settings.bridgeIp}"
    log.warn "Bridge port is: ${prefInt('bridgePort', 5000)}"
    log.warn "announcement timeout is: ${announceTimeout()}s (0 = disabled)"
    log.warn "request timeout is: ${prefInt('timeoutSec', 5)}s"
    log.warn "poll interval is: ${settings.pollMinutes} minutes (0 = disabled)"
    log.warn "warm colour temperature is: ${prefInt('ctMinKelvin', 2700)}K"
    log.warn "cool colour temperature is: ${prefInt('ctMaxKelvin', 6500)}K"
    log.warn "color pre-staging is: ${colorStaging == true}"
    log.warn "debug logging is: ${logEnable == true}"
    log.warn "description logging is: ${txtEnable == true}"
    purgeStaleAttributes()
    state.remove("lastLevel")
    forgetAnnouncedAddressIfTypedChanged()
    unschedule()
    schedulePoll()
    scheduleAnnounceCheck()
    if (logEnable) runIn(1800, "logsOff")
    runIn(2, "refresh")
}

// Retyping the Bridge IP or port drops the announced address so the typed
// one applies again until the Bridge's next announcement (within a minute):
// the way out of a stale announced address once the announcer is switched
// off. Saving any other preference leaves the announced address alone, so a
// save never sends commands to a typed address that has gone stale.
private void forgetAnnouncedAddressIfTypedChanged() {
    String typed = "${(settings.bridgeIp ?: '').toString().trim()}:${prefInt('bridgePort', 5000)}"
    String previous = state.typedAddress?.toString()
    state.typedAddress = typed
    if (previous == null || previous == typed) return
    if (state.bridgeIp != null || state.bridgePort != null) {
        logDebug "typed address changed to ${typed}; announced address ${state.bridgeIp}:${state.bridgePort} forgotten until the next announcement"
    }
    state.remove("bridgeIp")
    state.remove("bridgePort")
    state.remove("lastAnnounceAt")
    state.remove("lastSeenAt")
}

// Called from installed(); the status poll covers hub restarts.
void initialize() {
    logDebug "initialize()"
    scheduleAnnounceCheck()
    runIn(10, "refresh")
}

// Google Home types a device by its attribute set, and attribute values outlive the driver
// that created them, so remove the ones this version no longer declares.
private void purgeStaleAttributes() {
    ["colorMode"].each { String name ->
        try {
            if (device.currentValue(name, true) != null) {
                device.deleteCurrentState(name)
                logDebug "removed stale attribute ${name}"
            }
        } catch (Exception e) {
            logDebug "could not remove attribute ${name}: ${e.message}"
        }
    }
}

void logsOff() {
    log.warn "debug logging disabled..."
    device.updateSetting("logEnable", [value: "false", type: "bool"])
}

// LAN drivers must define parse(); nothing is pushed to this device.
void parse(String description) {
    logDebug "parse: ${description}"
}

private void schedulePoll() {
    String minutes = (settings.pollMinutes ?: "5").toString()
    switch (minutes) {
        case "1":
            runEvery1Minute("refresh")
            break
        case "5":
            runEvery5Minutes("refresh")
            break
        case "10":
            runEvery10Minutes("refresh")
            break
        case "15":
            runEvery15Minutes("refresh")
            break
        case "30":
            runEvery30Minutes("refresh")
            break
        default:
            logDebug "polling disabled"
    }
}

private void scheduleAnnounceCheck() {
    if (announceTimeout() > 0) {
        runEvery1Minute("checkAnnounce")
    } else {
        logDebug "announcement timeout disabled"
    }
}

private Integer announceTimeout() {
    return limitIntegerRange(prefInt("announceTimeoutSec", 200), 0, 86400)
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

// No level is sent: the Bridge remembers the last level itself (persisted
// across restarts) and applies it, or its configured default. Sending a
// Driver-side copy raced Google Home's setLevel, which arrives just before
// on() for a single slider move, and replayed the old level over the new.
void on() {
    logDebug "on()"
    sendBridge("/moonhalo/on" + paceQuery(null), [command: "on"])
}

void off() {
    logDebug "off()"
    sendBridge("/moonhalo/off" + paceQuery(null), [command: "off"])
}

// rate is forwarded as the transition query parameter; see paceQuery.
void setLevel(value, rate = null) {
    logDebug "setLevel(${value}, ${rate})"
    if (value == null) return
    Integer level = limitIntegerRange(value, 0, 100)
    if (level == null) {
        log.warn "${device.displayName}: setLevel ignored, '${value}' is not a number"
        return
    }
    if (level == 0) {
        // Level 0 is off, but its rate still travels: the Bridge dims out over it (0 snaps).
        sendBridge("/moonhalo/off" + paceQuery(rate), [command: "off"])
        return
    }
    sendBridge("/moonhalo/brightness/${level}" + paceQuery(rate), [command: "setLevel", level: level])
}

// tt is forwarded like setLevel's rate, on both requests when a level is
// given: brightness goes first and the colour request is sent from its
// reply, so the MoonHalo is on (and pre-staging does not apply) by then.
void setColorTemperature(value, level = null, tt = null) {
    logDebug "setColorTemperature(${value}, ${level}, ${tt})"
    if (value == null) return
    Integer ctMin = Math.max(1000, prefInt("ctMinKelvin", 2700))
    Integer ctMax = Math.max(1000, prefInt("ctMaxKelvin", 6500))
    if (ctMin > ctMax) {
        Integer swap = ctMin
        ctMin = ctMax
        ctMax = swap
    }
    Integer kelvin = limitIntegerRange(value, ctMin, ctMax)
    if (kelvin == null) {
        log.warn "${device.displayName}: setColorTemperature ignored, '${value}' is not a number"
        return
    }
    String ctPath = "/moonhalo/colortemp/${kelvin}"
    Integer lvl = (level == null) ? null : limitIntegerRange(level, 0, 100)
    if (lvl != null && lvl > 0) {
        sendBridge("/moonhalo/brightness/${lvl}" + paceQuery(tt), [command: "setColorTemperature", level: lvl, followUp: ctPath + paceQuery(tt)])
        return
    }
    String stage = stageQuery()
    sendBridge(ctPath + stage + paceQuery(tt, stage != ""), [command: "setColorTemperature", colorTemperature: kelvin])
}

void setColorTempStep(step) {
    logDebug "setColorTempStep(${step})"
    if (step == null) return
    Integer hardwareStep = limitIntegerRange(step, 1, 7)
    if (hardwareStep == null) {
        log.warn "${device.displayName}: setColorTempStep ignored, '${step}' is not a number"
        return
    }
    sendBridge("/moonhalo/colortemp/${hardwareStep}" + stageQuery(), [command: "setColorTempStep", step: hardwareStep])
}

void refresh() {
    logDebug "refresh()"
    sendBridge("/moonhalo/status", [command: "refresh"])
}

// ---------------------------------------------------------------------------
// Bridge address announcements (Maker API)
// ---------------------------------------------------------------------------

// Called by the Bridge through the Maker API: GET
// /apps/api/<app>/devices/<device>/setBridgeAddress/<ip>,<port>?access_token=...
// Stores the address for sendBridge(), stamps the announcement time for
// checkAnnounce(), and counts as proof the Bridge is up.
void setBridgeAddress(ip, port) {
    logDebug "setBridgeAddress(${ip}, ${port})"
    String address = (ip ?: "").toString().trim()
    if (!isIpv4(address)) {
        log.warn "${device.displayName}: setBridgeAddress ignored, '${ip}' is not an IPv4 address"
        return
    }
    Integer bridgePort = asInteger(port)
    if (bridgePort == null || bridgePort < 1 || bridgePort > 65535) {
        log.warn "${device.displayName}: setBridgeAddress ignored, '${port}' is not a port (1-65535)"
        return
    }
    String announced = "${address}:${bridgePort}"
    Boolean changed = device.currentValue("bridgeAddress") != announced
    Boolean first = (state.lastAnnounceAt == null)
    state.bridgeIp = address
    state.bridgePort = bridgePort
    state.lastAnnounceAt = now()
    state.lastSeenAt = state.lastAnnounceAt
    emitEvent("bridgeAddress", announced, null, "${device.displayName} bridgeAddress ${changed ? 'was set to' : 'is'} ${announced}", changed)
    markOnline()
    // A driver-code update alone never runs updated(), so the first
    // announcement after one arms the check itself.
    if (first) scheduleAnnounceCheck()
}

// Scheduled once a minute while the announcement timeout is enabled. Judges
// liveness by the last time anything was heard from the Bridge, announcement
// or reply, so announcements stopping while commands still work (announcer
// switched off, token changed) never fight the successful replies. Nothing
// happens until the first announcement has arrived, so a Bridge without the
// Maker API values is judged by the status poll alone.
void checkAnnounce() {
    Integer timeout = announceTimeout()
    if (timeout <= 0) return
    if (state.lastAnnounceAt == null) {
        logDebug "no announcement received yet"
        return
    }
    Long last = asLong(state.lastSeenAt) ?: asLong(state.lastAnnounceAt)
    Long age = (now() - last).intdiv(1000L)
    if (age > timeout) {
        markOffline("nothing heard from the Bridge for ${age}s, limit ${timeout}s")
    } else {
        logDebug "last heard from the Bridge ${age}s ago"
    }
}

private Boolean isIpv4(String text) {
    if (!text) return false
    return text.matches('^(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)(\\.(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)){3}$')
}

// "?stage=1" when colour pre-staging is on and the MoonHalo is not on:
// the Bridge then stores the colour without powering the halo.
private String stageQuery() {
    Boolean stage = (colorStaging == true) && (device.currentValue("switch") != "on")
    return stage ? "?stage=1" : ""
}

// "?transition=<value>" when value (a rate or tt) is a number, else
// "?sweep=<preference>" when Default transition is set, else "".
// queryStarted: the path already carries "?stage=1", so use "&".
private String paceQuery(Object value, Boolean queryStarted = false) {
    String separator = queryStarted ? "&" : "?"
    if (value != null) {
        String text = "${value}".toString().trim()
        if (text.isNumber()) return separator + "transition=${text}"
        logDebug "transition '${value}' is not a number; omitted"
    }
    String sweep = sweepSeconds()
    return (sweep == null) ? "" : separator + "sweep=${sweep}"
}

// The Default transition preference as text, or null if blank, not a number, or outside 0-60.
private String sweepSeconds() {
    Object value = settings["defaultTransitionSec"]
    if (value == null) return null
    String text = "${value}".toString().trim()
    if (text == "") return null
    if (!text.isNumber()) {
        logDebug "Default transition '${value}' is not a number; ignored, the Bridge default applies"
        return null
    }
    BigDecimal seconds = text.toBigDecimal()
    if (seconds < 0 || seconds > 60) {
        logDebug "Default transition ${text} is outside 0-60; ignored, the Bridge default applies"
        return null
    }
    return text
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

// One asynchronous GET to the Bridge. Never blocks; a thrown exception
// (bad URI, hub refusing the request) counts as the Bridge being offline.
// The address the Bridge announced wins over the typed preferences.
private void sendBridge(String path, Map data) {
    Map callbackData = (data ?: [:])
    String command = callbackData.command ?: "request"
    String ip = (state.bridgeIp ?: settings.bridgeIp ?: "").toString().trim()
    if (!ip) {
        log.warn "${device.displayName}: Bridge IP address is not set, ${command} ignored"
        return
    }
    Integer announcedPort = asInteger(state.bridgePort)
    Integer port = limitIntegerRange((announcedPort != null) ? announcedPort : prefInt("bridgePort", 5000), 1, 65535)
    Integer timeout = limitIntegerRange(prefInt("timeoutSec", 5), 1, 30)
    String uri = "http://${ip}:${port}${path}"
    callbackData = callbackData + [uri: uri]
    Map params = [uri: uri, contentType: "application/json", timeout: timeout]
    logDebug "${command}: GET ${uri}"
    try {
        asynchttpGet("bridgeCallback", params, callbackData)
    } catch (Exception e) {
        markOffline("${command} could not be sent: ${e.message}")
    }
}

// The AsyncResponse API is not documented, so every accessor is guarded:
// an error or non-200 reply marks the Bridge offline and touches nothing
// else; ok false marks online and logs the Bridge's message; ok true marks
// online and applies the returned state.
void bridgeCallback(resp, data) {
    String command = (data instanceof Map && data.command) ? data.command.toString() : "request"
    try {
        Boolean failed = false
        try {
            failed = (resp == null) || (resp.hasError() == true)
        } catch (Exception e) {
            failed = true
        }
        if (failed) {
            String message = null
            try {
                message = resp?.getErrorMessage()
            } catch (Exception e) {
                message = null
            }
            markOffline("${command} failed: ${message ?: 'no response'}")
            return
        }

        Integer status = null
        try {
            status = resp.status as Integer
        } catch (Exception e) {
            status = null
        }
        if (status != 200) {
            markOffline("${command} returned HTTP ${status}")
            return
        }

        Map json = parseReply(resp)
        if (json == null) {
            markOffline("${command} returned an unreadable reply")
            return
        }

        if (json.get("ok") != true) {
            markOnline()
            log.warn "${device.displayName}: Bridge rejected ${command}: ${json.get('error') ?: 'no error given'}"
            return
        }

        markOnline()
        Object halo = json.get("state")
        applyState((halo instanceof Map) ? (Map) halo : null, data)

        // The second half of setColorTemperature(ct, level): sent only once
        // the brightness request succeeded, so the MoonHalo is on.
        String followUp = (data instanceof Map && data.followUp) ? data.followUp.toString() : null
        if (followUp) {
            sendBridge(followUp, [command: command])
        }
    } catch (Exception e) {
        log.warn "${device.displayName}: error handling the Bridge reply to ${command}: ${e.message}"
    }
}

// resp.json first; if that fails, parse resp.data ourselves.
private Map parseReply(resp) {
    Object json = null
    try {
        json = resp.json
    } catch (Exception e) {
        json = null
    }
    if (!(json instanceof Map)) {
        try {
            Object raw = resp.data
            if (raw != null && raw.toString().trim()) {
                json = new groovy.json.JsonSlurper().parseText(raw.toString())
            }
        } catch (Exception e) {
            logDebug "reply body is not JSON: ${e.message}"
            json = null
        }
    }
    return (json instanceof Map) ? (Map) json : null
}

// ---------------------------------------------------------------------------
// State and events
// ---------------------------------------------------------------------------

// Emits switch, level, colorTemperature and colorName from the
// Bridge's state. Wording follows Hubitat's example drivers: "is" when the
// value is unchanged, "was turned" / "was set to" when it changed.
private void applyState(Map halo, Map data) {
    if (halo == null) {
        logDebug "reply carried no state"
        return
    }
    String name = device.displayName

    String power = halo.power?.toString()
    String switchValue = null
    if (power == "on" || power == "auto") {
        switchValue = "on"
    } else if (power == "off") {
        switchValue = "off"
    }
    if (switchValue != null) {
        Boolean changed = device.currentValue("switch") != switchValue
        emitEvent("switch", switchValue, null, "${name} ${changed ? 'was turned' : 'is'} ${switchValue}", changed)
    } else {
        logDebug "power is ${power}; switch left as it was"
    }

    Integer level = asInteger(halo.level)
    if (level != null) {
        Integer current = asInteger(device.currentValue("level"))
        Boolean changed = current != level
        emitEvent("level", level, "%", "${name} level ${changed ? 'was set to' : 'is'} ${level}%", changed)
    }

    Integer kelvin = asInteger(halo.colorTemperature)
    if (kelvin != null) {
        Integer current = asInteger(device.currentValue("colorTemperature"))
        Boolean changed = current != kelvin
        emitEvent("colorTemperature", kelvin, "°K", "${name} colorTemperature ${changed ? 'was set to' : 'is'} ${kelvin}°K", changed)

        String colorName = null
        try {
            colorName = convertTemperatureToGenericColorName(kelvin)
        } catch (Exception e) {
            logDebug "convertTemperatureToGenericColorName unavailable: ${e.message}"
        }
        if (colorName) {
            Boolean nameChanged = device.currentValue("colorName") != colorName
            emitEvent("colorName", colorName, null, "${name} color is ${colorName}", nameChanged)
        }
    }

}

private void emitEvent(String name, value, String unit, String descriptionText, Boolean changed) {
    if (changed) {
        logInfo(descriptionText)
    } else {
        logDebug(descriptionText)
    }
    Map event = [name: name, value: value, descriptionText: descriptionText]
    if (unit) event.unit = unit
    sendEvent(event)
}

// Offline is how a MoonHalo whose PC is powered down is shown. The warning
// is logged once, on the transition; repeats go to debug. switch and level
// are never touched here.
private void markOffline(String reason) {
    String current = device.currentValue("connectionState", true)
    if (current != "offline") {
        String descriptionText = "${device.displayName} connectionState was set to offline"
        sendEvent(name: "connectionState", value: "offline", descriptionText: descriptionText)
        log.warn "${device.displayName}: Bridge offline (${reason})"
    } else {
        logDebug "Bridge still offline (${reason})"
    }
}

private void markOnline() {
    state.lastSeenAt = now()
    String current = device.currentValue("connectionState", true)
    if (current != "online") {
        String descriptionText = "${device.displayName} connectionState was set to online"
        sendEvent(name: "connectionState", value: "online", descriptionText: descriptionText)
        log.info "${device.displayName}: Bridge online"
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Clamps value (Integer, BigDecimal, String) into min..max; null if it is
// not a number.
Integer limitIntegerRange(value, Integer min, Integer max) {
    Integer limit = asInteger(value)
    if (limit == null) return null
    return (limit < min) ? min : (limit > max) ? max : limit
}

// Integer from whatever the platform hands over (BigDecimal, Long, String,
// "50.0"); null when it cannot be read as a number.
private Integer asInteger(value) {
    if (value == null) return null
    if (value instanceof Number) return ((Number) value).intValue()
    String text = value.toString().trim()
    if (!text) return null
    try {
        return new BigDecimal(text).intValue()
    } catch (Exception e) {
        return null
    }
}

// Long from a state value (Long, Integer, BigDecimal or String); null when
// it cannot be read as a number.
private Long asLong(value) {
    if (value == null) return null
    if (value instanceof Number) return ((Number) value).longValue()
    try {
        return new BigDecimal(value.toString().trim()).longValue()
    } catch (Exception e) {
        return null
    }
}

// A number preference; Hubitat may store it as BigDecimal or String.
private Integer prefInt(String name, Integer defaultValue) {
    Integer parsed = asInteger(settings[name])
    return (parsed == null) ? defaultValue : parsed
}

private void logDebug(String message) {
    if (logEnable) log.debug "${device.displayName}: ${message}"
}

private void logInfo(String message) {
    if (txtEnable) log.info "${message}"
}
