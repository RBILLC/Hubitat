/**
 * BenQ MoonHalo Bridge
 *
 * Presents the MoonHalo backlight of a BenQ RD280UG monitor to the Hub as a
 * dimmable colour-temperature light. The Driver never talks to the monitor:
 * every command is one short asynchronous HTTP GET to the Bridge, the service
 * on the Windows PC the monitor is attached to, using its JSON contract:
 * /moonhalo/on[?level=1-100], /moonhalo/off, /moonhalo/brightness/<0-100>
 * (0 = off), /moonhalo/colortemp/<value>[?stage=1] (1-7 is a hardware step,
 * 1000 or more is Kelvin) and /moonhalo/status. Each reply is
 * {"ok": true, "state": {power, level, brightnessStep, colorTemperature,
 * colorTempStep, monitor}} or {"ok": false, "error": "..."}.
 *
 * Author: RBILLC
 * Import URL: https://raw.githubusercontent.com/RBILLC/Hubitat/main/Drivers/BenQ_MoonHalo_Bridge_Driver.groovy
 *
 * Behaviour:
 * - The connectionState data value goes offline when the Bridge cannot be reached, like
 *   a bulb with no power; switch and level keep their last known values.
 * - Attribute events are emitted only after the Bridge confirms a request,
 *   from the state carried in its reply. Nothing is assumed optimistically.
 * - Transition times (setLevel duration, setColorTemperature transitionTime)
 *   are accepted and ignored; the MoonHalo has no fades.
 * - on() restores the last level the Bridge reported; with none remembered
 *   it asks the Bridge for its default.
 * - setColorTemperature while off turns the MoonHalo on, unless colour
 *   pre-staging is enabled, in which case the colour is stored for later.
 * - No hardware knowledge lives here: no VCP registers, no step maths. The
 *   only hardware-shaped value is the 1-7 step passed through by
 *   setColorTempStep.
 *
 * Version: 0.0.5 (pre-release; 1.0.0 on public announcement). The Bridge carries the same number.
 *
 * Changelog:
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
        capability "ColorMode"
        capability "Bulb"
        capability "Refresh"


        command "setColorTempStep", [[name: "Step*", type: "NUMBER", description: "Hardware colour temperature step, 1 (warm) to 7 (cool)"]]
    }

    preferences {
        input name: "bridgeIp", type: "text", title: "Bridge IP address", description: "IPv4 address of the PC running the MoonHalo Bridge", required: true
        input name: "bridgePort", type: "number", title: "Bridge port", defaultValue: 5000, range: "1..65535"
        input name: "timeoutSec", type: "number", title: "Request timeout (seconds)", defaultValue: 5, range: "1..30"
        input name: "pollMinutes", type: "enum", title: "Poll interval", description: "How often the Hub asks the Bridge for its status", options: [["0": "Disabled"], ["1": "1 minute"], ["5": "5 minutes"], ["10": "10 minutes"], ["15": "15 minutes"], ["30": "30 minutes"]], defaultValue: "5"
        input name: "ctMinKelvin", type: "number", title: "Warm colour temperature (Kelvin)", defaultValue: 2700, range: "1000..20000"
        input name: "ctMaxKelvin", type: "number", title: "Cool colour temperature (Kelvin)", defaultValue: 6500, range: "1000..20000"
        input name: "colorStaging", type: "bool", title: "Enable color pre-staging", description: "Store a colour temperature while the MoonHalo stays off", defaultValue: false
        input name: "logEnable", type: "bool", title: "Enable debug logging", defaultValue: true
        input name: "txtEnable", type: "bool", title: "Enable descriptionText logging", defaultValue: true
    }
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

void installed() {
    log.info "installed..."
    device.updateDataValue("connectionState", "unknown")
    sendEvent(name: "colorMode", value: "CT", descriptionText: "${device.displayName} colorMode is CT")
    initialize()
}

void updated() {
    log.info "updated..."
    log.warn "Bridge IP is: ${settings.bridgeIp}"
    log.warn "Bridge port is: ${prefInt('bridgePort', 5000)}"
    log.warn "request timeout is: ${prefInt('timeoutSec', 5)}s"
    log.warn "poll interval is: ${settings.pollMinutes} minutes (0 = disabled)"
    log.warn "warm colour temperature is: ${prefInt('ctMinKelvin', 2700)}K"
    log.warn "cool colour temperature is: ${prefInt('ctMaxKelvin', 6500)}K"
    log.warn "color pre-staging is: ${colorStaging == true}"
    log.warn "debug logging is: ${logEnable == true}"
    log.warn "description logging is: ${txtEnable == true}"
    purgeStaleAttributes()
    unschedule()
    schedulePoll()
    if (logEnable) runIn(1800, "logsOff")
    runIn(2, "refresh")
}

// Called from installed(); the status poll covers hub restarts.
void initialize() {
    logDebug "initialize()"
    runIn(10, "refresh")
}

// Google Home types a device by its attribute set, and attribute values outlive the driver
// that created them, so remove the ones this version no longer declares.
private void purgeStaleAttributes() {
    ["connectionState"].each { String name ->
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

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

void on() {
    logDebug "on()"
    Integer lastLevel = asInteger(state.lastLevel)
    if (lastLevel != null && lastLevel >= 1 && lastLevel <= 100) {
        sendBridge("/moonhalo/brightness/${lastLevel}", [command: "on", level: lastLevel])
    } else {
        sendBridge("/moonhalo/on", [command: "on"])
    }
}

void off() {
    logDebug "off()"
    sendBridge("/moonhalo/off", [command: "off"])
}

// rate (transition duration) is accepted and ignored.
void setLevel(value, rate = null) {
    logDebug "setLevel(${value}, ${rate})"
    if (value == null) return
    Integer level = limitIntegerRange(value, 0, 100)
    if (level == null) {
        log.warn "${device.displayName}: setLevel ignored, '${value}' is not a number"
        return
    }
    if (level == 0) {
        off()
        return
    }
    sendBridge("/moonhalo/brightness/${level}", [command: "setLevel", level: level])
}

// tt (transition time) is accepted and ignored. When a level is given the
// brightness request goes first and the colour temperature request is sent
// from its reply, so the Bridge sees them in order and the MoonHalo is on
// (and pre-staging does not apply) by the time the colour arrives.
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
        sendBridge("/moonhalo/brightness/${lvl}", [command: "setColorTemperature", level: lvl, followUp: ctPath])
        return
    }
    sendBridge(ctPath + stageQuery(), [command: "setColorTemperature", colorTemperature: kelvin])
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

// "?stage=1" when colour pre-staging is on and the MoonHalo is not on:
// the Bridge then stores the colour without powering the halo.
private String stageQuery() {
    Boolean stage = (colorStaging == true) && (device.currentValue("switch") != "on")
    return stage ? "?stage=1" : ""
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

// One asynchronous GET to the Bridge. Never blocks; a thrown exception
// (bad URI, hub refusing the request) counts as the Bridge being offline.
private void sendBridge(String path, Map data) {
    Map callbackData = (data ?: [:])
    String command = callbackData.command ?: "request"
    String ip = (settings.bridgeIp ?: "").toString().trim()
    if (!ip) {
        log.warn "${device.displayName}: Bridge IP address is not set, ${command} ignored"
        return
    }
    Integer port = limitIntegerRange(prefInt("bridgePort", 5000), 1, 65535)
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

// Emits switch, level, colorTemperature, colorName and colorMode from the
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
        if (level > 0) state.lastLevel = level
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

    if (device.currentValue("colorMode") != "CT") {
        emitEvent("colorMode", "CT", null, "${name} colorMode is CT", true)
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
// Connection state is kept as a device data value (shown under "Data" on the device page)
// rather than an attribute while the Google Home typing is being settled: Google Home types a
// device by its attribute set and rejects sets it does not recognise.
private void markOffline(String reason) {
    String current = device.getDataValue("connectionState")
    if (current != "offline") {
        device.updateDataValue("connectionState", "offline")
        log.warn "${device.displayName}: Bridge offline (${reason})"
    } else {
        logDebug "Bridge still offline (${reason})"
    }
}

private void markOnline() {
    String current = device.getDataValue("connectionState")
    if (current != "online") {
        device.updateDataValue("connectionState", "online")
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
