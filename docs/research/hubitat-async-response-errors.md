# Hubitat AsyncResponse on a non-2xx reply

Research pass for issue #39 (2026-09-14). Question: when `asynchttpGet` gets an HTTP 500
whose body is JSON, how does the callback's response object expose it? The official docs do
not describe the object at all (see `hubitat-driver-facilities.md`, section 1 and open
question 1), so this is from the community forum and from this repo's own hub log.

## Findings

1. **`hasError()` is true for a 4xx/5xx reply and `getErrorMessage()` is the HTTP reason
   phrase.** Evidence from this repo: during the 2026-09-14 outage the Driver (0.0.11) logged
   `Bridge offline (setLevel failed: INTERNAL SERVER ERROR)`; that text comes from the
   `hasError()` branch of `bridgeCallback`, which prints `getErrorMessage()`. Hubitat staff
   (Chuck Schwer) give `if(response.hasError()) { log.warn(response.getErrorMessage()) }` as
   the error-handling pattern in
   https://community.hubitat.com/t/408-response-from-async-http-actions-doesnt-bring-data-map/36753,
   and note that status 408 "will come back anytime an exception happens in the async client
   code" (a timeout or refused connection, not a real 408 from the server).

2. **The body of an error reply is in `getErrorData()`** (a String). A user in
   https://community.hubitat.com/t/async-http-response-geterrorjson-exception-but-geterrordata-shows-json/73094
   reported `getErrorData()` returning the JSON body of a 404 while `getErrorJson()` threw
   `java.lang.Exception: No response data exists for async request`; a developer-flaired poster
   called that a bug. Whether it has since been fixed is not recorded, so a driver should try
   `errorJson` and fall back to parsing `errorData` itself.

3. `getData()` / `getJson()` on an error reply are not documented anywhere found; treat them as
   possibly null or throwing and guard every accessor, as the Driver already does.

## Applied in the Driver (0.0.12)

`parseReply` tries `resp.json`, `resp.errorJson`, `resp.data`, `resp.errorData` in that order,
each guarded; a body that parses to a map with an `ok` key is a Bridge reply whatever the HTTP
status, so a 500 keeps `bridgeLink` online and sets `monitorLink` from its `monitor` object.
Only no reply, an unreadable body, or a body without `ok` marks `bridgeLink` offline.
