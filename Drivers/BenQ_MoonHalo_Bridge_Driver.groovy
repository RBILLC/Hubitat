/**
 * BenQ MoonHalo Bridge
 *
 * Presents the MoonHalo backlight of a BenQ RD280UG monitor to the Hub as a
 * dimmable color-temperature light. Every command is one asynchronous HTTP
 * GET to the Bridge, the service on the PC the monitor is attached to; the
 * Bridge does the DDC/CI. Contract: Bridges/BenQ_MoonHalo/README.md, HTTP API.
 *
 * Author: RBILLC
 * Import URL: https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy
 *
 * - bridgeLink: whether the Hub could reach the Bridge; any reply, a 500
 *   included, is online. Offline leaves switch and level as they were.
 * - monitorLink: the Bridge's last word on the monitor (ok, failed, unknown);
 *   unreachable while bridgeLink is offline. Commands are sent regardless.
 * - Attribute events come only from the state in the Bridge's reply.
 * - setLevel's rate or setColorTemperature's tt goes to the Bridge as transition
 *   (seconds; 0 snaps); without one the Default transition preference goes as sweep.
 * - on() sends no level; the Bridge restores the level it remembers.
 * - setColorTemperature while off turns the MoonHalo on unless color
 *   pre-staging is enabled. The Kelvin goes to the Bridge as sent (floor 1000);
 *   the Bridge clamps it to its own kelvin_min..kelvin_max and maps it to a step.
 * - The Bridge announces its address through the Maker API (setBridgeAddress);
 *   it wins over the typed IP, and silence past the announcement timeout is offline.
 * - State: announcedIp/announcedPort, lastSeen/lastAnnounce (epoch twins
 *   lastSeenAt/lastAnnounceAt), lastMonitorError/lastMonitorErrorAt,
 *   bridgeVersion, typedAddress.
 *
 * Version: 0.0.16 (pre-release; 1.0.0 on public announcement). The Bridge is versioned
 * separately; every reply reports its number (bridgeVersion). Minimum Bridge version: 0.0.9
 * (MIN_BRIDGE_VERSION); it moves only when the Driver reads something an older Bridge does not send.
 *
 * Changelog:
 * 2026-10-08 0.0.16 - warmKelvin and coolKelvin preferences dropped (removed on save): the Bridge owns
 *                     the Kelvin range; every preference has a description; American spelling
 *                     throughout (issue #48)
 * 2026-10-08 0.0.15 - preferences renamed: timeoutSec -> requestTimeoutSec, ctMinKelvin -> warmKelvin,
 *                     ctMaxKelvin -> coolKelvin, pollMinutes -> pollIntervalMin (retyped once, old
 *                     settings removed on save); state monitorLinkError/monitorLinkErrorAt ->
 *                     lastMonitorError/lastMonitorErrorAt (values carried over); comments trimmed,
 *                     explanations moved to the Bridge README (issue #41)
 * 2026-09-16 0.0.14 - bridgeVersion state from the version field of every reply, checked against
 *                     the minimum Bridge version 0.0.9: too old or missing is shown in place with
 *                     one warning, newer is never flagged (issue #43)
 * 2026-09-16 0.0.13 - monitorLink reads unreachable while bridgeLink is offline, set in the same
 *                     event batch and restored by the first Bridge reply; monitorLinkError and
 *                     monitorLinkErrorAt are untouched (issue #42)
 * 2026-09-14 0.0.12 - bridgeLink replaces connectionState; monitorLink from the Bridge's monitor
 *                     object; a 500 keeps bridgeLink online; readable lastSeen/lastAnnounce and
 *                     announcedIp/announcedPort state (issue #39)
 * 2026-09-08 0.0.11 - Default transition is whole milliseconds, default 300: the decimal input would
 *                     not accept values under 1.0 on the device page (issue #37)
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
 *                    full color and gives a CT-only driver no temperature trait (issue #21)
 * 2026-09-04 0.0.5 - Google Home typing test: colorMode "CT" back, still no custom attribute;
 *                    0.0.4 was accepted but typed as a plain dimmer (issue #21)
 * 2026-09-04 0.0.4 - Google Home typing test: attribute set reduced to the CT bulb's (switch,
 *                    level, colorTemperature, colorName); connectionState kept as a data value;
 *                    stale colorMode/connectionState attributes purged on save (issue #21)
 * 2026-09-04 0.0.3 - Restore ColorMode (colorMode "CT"): without it Google Home typed the device
 *                    as a plain dimmer with no color-temperature control; Initialize stays out
 *                    (issue #21)
 * 2026-09-04 0.0.2 - Drop ColorMode and Initialize capabilities: still rejected by Hubitat's
 *                    Google Home app with Bulb alone; accepted CT-only drivers declare neither
 *                    (issue #21)
 * 2026-09-04 0.0.1 - Declare Bulb instead of Light: Hubitat's Google Home app rejected the
 *                    device ("not supported by Google Home"); its own CT-only example driver and
 *                    docs use Bulb (issue #21)
 * 2026-09-04 0.0.0 - Initial pre-release (issue #19)
 */

import groovy.transform.Field

// Oldest Bridge this Driver reads; see the header's Version paragraph.
@Field static final String MIN_BRIDGE_VERSION = "0.0.9"

metadata {
    definition (name: "BenQ MoonHalo Bridge", namespace: "rbillc", author: "RBILLC", importUrl: "https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy") {
        capability "Actuator"
        capability "Switch"
        capability "SwitchLevel"
        capability "ColorTemperature"
        capability "Bulb"
        capability "Refresh"


        attribute "bridgeLink", "enum", ["unknown", "online", "offline"]
        attribute "monitorLink", "enum", ["unknown", "ok", "failed", "unreachable"]
        attribute "bridgeAddress", "string"

        command "setColorTempStep", [[name: "Step*", type: "NUMBER", description: "Hardware color temperature step, 1 (warm) to 7 (cool)"]]
        command "setBridgeAddress", [
            [name: "IP address*", type: "STRING", description: "IPv4 address the Bridge is listening on; sent by the Bridge itself through the Maker API"],
            [name: "Port*", type: "NUMBER", description: "TCP port the Bridge is listening on, 1-65535"]
        ]
    }

    preferences {
        input name: "bridgeIp", type: "text", title: "Bridge IP address", description: "IPv4 address of the PC running the Bridge. Used until the Bridge announces its own address.", required: true
        input name: "bridgePort", type: "number", title: "Bridge port", description: "Port the Bridge listens on (port in its config.json). Used until the Bridge announces its own.", defaultValue: 5000, range: "1..65535"
        input name: "announceTimeoutSec", type: "number", title: "Announce timeout (seconds)", description: "Mark the Bridge offline when neither an announcement nor a reply has arrived for this long. 0 disables. Set it above the Bridge's announce_seconds.", defaultValue: 200, range: "0..86400"
        input name: "requestTimeoutSec", type: "number", title: "Request timeout (seconds)", description: "Seconds to wait for the Bridge to answer a command before marking it offline.", defaultValue: 5, range: "1..30"
        input name: "pollIntervalMin", type: "enum", title: "Poll interval", description: "How often to ask the Bridge for its status.", options: [["0": "Disabled"], ["1": "1 minute"], ["5": "5 minutes"], ["10": "10 minutes"], ["15": "15 minutes"], ["30": "30 minutes"]], defaultValue: "5"
        input name: "colorStaging", type: "bool", title: "Enable color pre-staging", description: "Accept a color temperature while the MoonHalo is off without turning it on.", defaultValue: false
        input name: "defaultTransitionMs", type: "number", title: "Default transition (ms)", description: "Time a full brightness sweep takes when a command carries no rate. 0 snaps; blank uses the Bridge default.", defaultValue: 300, range: "0..60000"
        input name: "logEnable", type: "bool", title: "Enable debug logging", defaultValue: true
        input name: "txtEnable", type: "bool", title: "Enable descriptionText logging", defaultValue: true
    }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

void installed() {
    log.info "installed..."
    sendEvent(name: "bridgeLink", value: "unknown", descriptionText: "${device.displayName} bridgeLink is unknown")
    sendEvent(name: "monitorLink", value: "unknown", descriptionText: "${device.displayName} monitorLink is unknown")
    initialize()
}

void updated() {
    log.info "updated..."
    log.warn "Bridge IP is: ${settings.bridgeIp}"
    log.warn "Bridge port is: ${prefInt('bridgePort', 5000)}"
    log.warn "announcement timeout is: ${announceTimeout()}s (0 = disabled)"
    log.warn "request timeout is: ${prefInt('requestTimeoutSec', 5)}s"
    log.warn "poll interval is: ${settings.pollIntervalMin} minutes (0 = disabled)"
    log.warn "color pre-staging is: ${colorStaging == true}"
    log.warn "debug logging is: ${logEnable == true}"
    log.warn "description logging is: ${txtEnable == true}"
    purgeStaleAttributes()
    purgeStaleSettings()
    ["lastLevel", "bridgeIp", "bridgePort"].each { String key -> state.remove(key) }
    renameStaleState()
    forgetAnnouncedAddressIfTypedChanged()
    unschedule()
    schedulePoll()
    scheduleAnnounceCheck()
    if (logEnable) runIn(1800, "logsOff")
    runIn(2, "refresh")
}

// Retyping the IP or port drops the announced address until the next
// announcement; any other save keeps it (Bridge README, Letting the Hub find the Bridge).
private void forgetAnnouncedAddressIfTypedChanged() {
    String typed = "${(settings.bridgeIp ?: '').toString().trim()}:${prefInt('bridgePort', 5000)}"
    String previous = state.typedAddress?.toString()
    state.typedAddress = typed
    if (previous == null || previous == typed) return
    if (state.announcedIp != null || state.announcedPort != null) {
        logDebug "typed address changed to ${typed}; announced address ${state.announcedIp}:${state.announcedPort} forgotten until the next announcement"
    }
    ["announcedIp", "announcedPort", "lastAnnounceAt", "lastAnnounce", "lastSeenAt", "lastSeen", "bridgeVersion"].each { String key ->
        state.remove(key)
    }
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
    ["colorMode", "connectionState"].each { String name ->
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

// Settings this version no longer declares linger until removed: the ones
// renamed in 0.0.15 and the Kelvin range dropped in 0.0.16.
private void purgeStaleSettings() {
    ["timeoutSec", "ctMinKelvin", "ctMaxKelvin", "pollMinutes", "warmKelvin", "coolKelvin"].each { String name ->
        try {
            device.removeSetting(name)
        } catch (Exception e) {
            logDebug "could not remove setting ${name}: ${e.message}"
        }
    }
}

// State keys renamed in 0.0.15: carry the value over once, then drop the old key.
private void renameStaleState() {
    [monitorLinkError: "lastMonitorError", monitorLinkErrorAt: "lastMonitorErrorAt"].each { String from, String to ->
        if (state[from] != null && state[to] == null) state[to] = state[from]
        state.remove(from)
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
    String minutes = (settings.pollIntervalMin ?: "5").toString()
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

// No level is sent: the Bridge restores the level it remembers (Bridge README, /moonhalo/on).
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

// tt travels like setLevel's rate, on both requests when a level is given:
// brightness first, then color from its reply, so the MoonHalo is on by then.
void setColorTemperature(value, level = null, tt = null) {
    logDebug "setColorTemperature(${value}, ${level}, ${tt})"
    if (value == null) return
    // Floor 1000: the Bridge reads 1-7 as a hardware step and >= 1000 as Kelvin,
    // which it clamps to its own range before mapping to a step.
    Integer kelvin = limitIntegerRange(value, 1000, Integer.MAX_VALUE)
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

// Called by the Bridge through the Maker API. Stores the address for sendBridge(),
// stamps the time for checkAnnounce(), and counts as proof the Bridge is up.
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
    state.announcedIp = address
    state.announcedPort = bridgePort
    Long at = now()
    state.lastAnnounceAt = at
    state.lastAnnounce = formatTime(at)
    emitEvent("bridgeAddress", announced, null, "${device.displayName} bridgeAddress ${changed ? 'was set to' : 'is'} ${announced}", changed)
    markOnline()
    // A driver-code update alone never runs updated(), so the first
    // announcement after one arms the check itself.
    if (first) scheduleAnnounceCheck()
}

// Once a minute while the timeout is enabled: offline when nothing, announcement
// or reply, was heard within it. Idle until the first announcement has arrived.
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

// "?stage=1" when color pre-staging is on and the MoonHalo is not on:
// the Bridge then stores the color without powering the halo.
private String stageQuery() {
    Boolean stage = (colorStaging == true) && (device.currentValue("switch") != "on")
    return stage ? "?stage=1" : ""
}

// "?transition=<value>" when value (a rate or tt) is a number, else "?sweep=<preference>"
// when Default transition is set, else ""; queryStarted means the path already has "?stage=1".
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

// The Default transition preference (ms) as seconds text for the sweep query, or null if
// blank, not a number, or outside 0-60000.
private String sweepSeconds() {
    Object value = settings["defaultTransitionMs"]
    if (value == null) return null
    String text = "${value}".toString().trim()
    if (text == "") return null
    if (!text.isNumber()) {
        logDebug "Default transition '${value}' is not a number; ignored, the Bridge default applies"
        return null
    }
    BigDecimal ms = text.toBigDecimal()
    if (ms < 0 || ms > 60000) {
        logDebug "Default transition ${text} ms is outside 0-60000; ignored, the Bridge default applies"
        return null
    }
    return (ms / 1000).stripTrailingZeros().toPlainString()
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

// One asynchronous GET to the Bridge; a thrown exception (bad URI, hub refusing the
// request) counts as offline. The announced address wins over the typed preferences.
private void sendBridge(String path, Map data) {
    Map callbackData = (data ?: [:])
    String command = callbackData.command ?: "request"
    String ip = (state.announcedIp ?: settings.bridgeIp ?: "").toString().trim()
    if (!ip) {
        log.warn "${device.displayName}: Bridge IP address is not set, ${command} ignored"
        return
    }
    Integer announcedPort = asInteger(state.announcedPort)
    Integer port = limitIntegerRange((announcedPort != null) ? announcedPort : prefInt("bridgePort", 5000), 1, 65535)
    Integer timeout = limitIntegerRange(prefInt("requestTimeoutSec", 5), 1, 30)
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

// Any reply, a 500 included, keeps bridgeLink online; no reply or a body without "ok"
// marks it offline. The AsyncResponse API is undocumented, so every accessor is guarded.
void bridgeCallback(resp, data) {
    String command = (data instanceof Map && data.command) ? data.command.toString() : "request"
    try {
        Map json = parseReply(resp)
        if (json == null || !json.containsKey("ok")) {
            markOffline("${command} got no Bridge reply (${replyFailure(resp)})")
            return
        }

        markOnline()
        applyMonitorLink(json.get("monitor"))
        applyBridgeVersion(json.get("version"))
        if (json.get("ok") != true) {
            log.warn "${device.displayName}: Bridge rejected ${command}: ${json.get('error') ?: 'no error given'}"
            return
        }

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

// The reply body as a map, or null. A non-2xx reply keeps its body in errorData
// (errorJson has thrown on some hubs); see docs/research/hubitat-async-response-errors.md.
private Map parseReply(resp) {
    if (resp == null) return null
    Map json = readMap { resp.json }
    if (json == null) json = readMap { resp.errorJson }
    if (json == null) json = readMap { parseJsonText(resp.data) }
    if (json == null) json = readMap { parseJsonText(resp.errorData) }
    return json
}

private Map readMap(Closure read) {
    try {
        Object value = read()
        return (value instanceof Map) ? (Map) value : null
    } catch (Exception e) {
        return null
    }
}

private Object parseJsonText(Object raw) {
    if (raw == null || !raw.toString().trim()) return null
    return new groovy.json.JsonSlurper().parseText(raw.toString())
}

// "HTTP 408, Request Timeout" or "no response", for the offline reason.
private String replyFailure(resp) {
    if (resp == null) return "no response"
    List parts = []
    try { if (resp.status != null) parts << "HTTP ${resp.status}" } catch (Exception e) { }
    try { if (resp.getErrorMessage()) parts << resp.getErrorMessage() } catch (Exception e) { }
    return parts ? parts.join(", ") : "no response"
}

// ---------------------------------------------------------------------------
// State and events
// ---------------------------------------------------------------------------

// switch, level, colorTemperature and colorName from the Bridge's state. Wording as in
// Hubitat's example drivers: "is" when unchanged, "was turned" / "was set to" when changed.
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

// monitorLink from a reply's monitor object: one warning on the transition to failed,
// debug on repeats, info on recovery; the last error and its time go to state.
private void applyMonitorLink(Object monitor) {
    if (!(monitor instanceof Map)) return
    Map reported = (Map) monitor
    String value = reported.link?.toString()
    if (!(value in ["ok", "failed", "unknown"])) return
    String name = device.displayName
    String current = device.currentValue("monitorLink", true)
    Boolean changed = current != value
    if (value == "failed") {
        String error = reported.error?.toString() ?: "no error given"
        state.lastMonitorError = error
        state.lastMonitorErrorAt = formatIso(reported.at?.toString()) ?: formatTime(now())
        if (changed) {
            log.warn "${name}: Monitor link failed (${error})"
        } else {
            logDebug "Monitor link still failed (${error})"
        }
    } else if (changed) {
        log.info "${name}: Monitor link ${value}"
    }
    if (changed) {
        sendEvent(name: "monitorLink", value: value, descriptionText: "${name} monitorLink was set to ${value}")
    }
}

// bridgeVersion from a reply's version field. Below MIN_BRIDGE_VERSION, or absent, it is
// shown in place with one warning on the transition, debug on repeats; info when it changes.
private void applyBridgeVersion(Object version) {
    String reported = version?.toString()?.trim() ?: "unknown"
    Boolean tooOld = !isVersionAtLeast(reported, MIN_BRIDGE_VERSION)
    String shown = tooOld ? "${reported} (Driver needs ${MIN_BRIDGE_VERSION} or later)" : reported
    if (state.bridgeVersion?.toString() == shown) {
        if (tooOld) logDebug "Bridge version still ${shown}"
        return
    }
    state.bridgeVersion = shown
    if (tooOld) {
        log.warn "${device.displayName}: Bridge version ${shown}"
    } else {
        log.info "${device.displayName}: Bridge version ${shown}"
    }
}

// Dotted versions compared numerically per segment (0.0.10 is newer than
// 0.0.9); missing segments count as 0; an unparsable version is never enough.
private Boolean isVersionAtLeast(String version, String minimum) {
    List<Integer> have = versionSegments(version)
    List<Integer> need = versionSegments(minimum)
    if (have == null || need == null) return false
    int length = Math.max(have.size(), need.size())
    for (int i = 0; i < length; i++) {
        Integer a = (i < have.size()) ? have[i] : 0
        Integer b = (i < need.size()) ? need[i] : 0
        if (a != b) return a > b
    }
    return true
}

private List<Integer> versionSegments(String version) {
    if (!version) return null
    List<Integer> segments = []
    for (String part in version.split("\\.")) {
        if (!part.isInteger()) return null
        segments << part.toInteger()
    }
    return segments
}

// One warning on the transition to offline, debug on repeats; switch and level are untouched.
private void markOffline(String reason) {
    String current = device.currentValue("bridgeLink", true)
    if (current != "offline") {
        String descriptionText = "${device.displayName} bridgeLink was set to offline"
        sendEvent(name: "bridgeLink", value: "offline", descriptionText: descriptionText)
        log.warn "${device.displayName}: Bridge link offline (${reason})"
    } else {
        logDebug "Bridge link still offline (${reason})"
    }
    markMonitorUnreachable()
}

// The Bridge cannot be asked, so its last word about the monitor is not current.
// lastMonitorError/lastMonitorErrorAt stay; the first reply restores monitorLink.
private void markMonitorUnreachable() {
    String name = device.displayName
    if (device.currentValue("monitorLink", true) == "unreachable") return
    log.info "${name}: Monitor link unreachable"
    sendEvent(name: "monitorLink", value: "unreachable", descriptionText: "${name} monitorLink was set to unreachable")
}

private void markOnline() {
    Long at = now()
    state.lastSeenAt = at
    state.lastSeen = formatTime(at)
    String current = device.currentValue("bridgeLink", true)
    if (current != "online") {
        String descriptionText = "${device.displayName} bridgeLink was set to online"
        sendEvent(name: "bridgeLink", value: "online", descriptionText: descriptionText)
        log.info "${device.displayName}: Bridge link online"
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

// "yyyy-MM-dd HH:mm:ss" in the hub's time zone; null for a null time.
private String formatTime(Long millis) {
    if (millis == null) return null
    return new Date(millis).format("yyyy-MM-dd HH:mm:ss", location.timeZone)
}

// The Bridge's ISO 8601 time with offset ("2026-09-14T17:40:12-04:00") in the
// hub's time zone; the text as sent if it cannot be parsed; null for none.
private String formatIso(String iso) {
    if (!iso) return null
    try {
        return formatTime(Date.parse("yyyy-MM-dd'T'HH:mm:ssXXX", iso).time)
    } catch (Exception e) {
        return iso
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
