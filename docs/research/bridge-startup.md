# Bridge startup: how should the MoonHalo Bridge keep running on Windows?

Research question: how do existing Hubitat PC-helper integrations keep their Windows-side helper
running, what do the ones that touch the interactive desktop/display do differently, and which of
a Windows service (NSSM or native), a logon-triggered scheduled task, or a Startup-folder shortcut
should the MoonHalo Bridge recommend, given that it calls `EnumDisplayMonitors`/`GetMonitorInfoW`
(user32.dll) and the dxva2 Monitor Configuration API to write DDC/CI to an attached monitor?

## One-paragraph answer

No surveyed Hubitat PC-helper needs the interactive desktop the way the MoonHalo Bridge does —
every one of them talks to the hub or a broker over a socket, and the one Python-based, most
similar precedent (EventGhost/PC Controller) documents no persistence mechanism at all, so there
is no existing "helper that touches the display" to copy; the choice has to be made from the
general Windows facts. Those facts point one direction: Microsoft's own services documentation
states plainly that "by default, services use a noninteractive window station and cannot interact
with the user" and that "all services run in Terminal Services session 0," and while no
Monitor-Configuration-API page says whether `EnumDisplayMonitors`/`SetVCPFeature` specifically
fail from session 0, the adjacent, still-live UMDF guidance says a session-0 process should avoid
`user32.dll` calls as "a general rule," and third-party evidence (a GitLab Runner issue,
independently, not about DDC/CI at all) shows Windows deliberately gives session-0 processes a
degraded, non-native display surface (screen resolution capped at 1024x768) precisely because
session 0 is not the interactive desktop. A logon-triggered Scheduled Task run only while the user
is logged on is the one method of the four that is *documented* to run in the same session as the
interactive user and therefore guaranteed to see the real display; a Task Scheduler task, unlike
the Startup folder, also gets a documented restart-on-failure setting and can be created for a
standard, non-admin session (the account creating and running its own task does not need to be an
Administrator — only the general "manage all tasks on this computer" permission needs the
Administrators group, per Microsoft's own `schtasks` permissions note, and creating a task that
runs as yourself is the normal case) and a hidden window via `pythonw`. **Recommendation: use the
logon-triggered Scheduled Task (`schtasks /create ... /sc onlogon`), not the NSSM/native service,**
as the Bridge README already documents as the fallback — treat it as the primary method for this
project rather than the fallback, because the session-0 risk that would justify trying the service
first is real, undocumented for this exact API, and only resolvable by the empirical test the
Bridge's own README already prescribes.

## Integrations surveyed

| Integration | Run method on Windows | Needs interactive desktop? | Source |
|---|---|---|---|
| Homebridge Hubitat plugins (jvmahon/homebridge-hubitat, tonesto7, danTapps) | `hb-service install` (documented on the Homebridge Windows wiki); underlying Windows service mechanism not documented | No — plugin only makes outbound HTTP calls to the hub's Maker API | [Install Homebridge on Windows 10 wiki](https://github.com/homebridge/homebridge/wiki/Install-Homebridge-on-Windows-10); [Homebridge Service Command](https://github.com/homebridge/homebridge-config-ui-x/wiki/Homebridge-Service-Command) |
| hubitat-mqtt-bridge (jeubanks) | Docker (`docker run`) or plain `npm` install; no Windows-specific service instructions documented | No — HTTP listener + MQTT republish, no display/UI work | [hubitat-mqtt-bridge README](https://raw.githubusercontent.com/jeubanks/hubitat-mqtt-bridge/master/README.md) |
| node-red-contrib-hubitat (fblackburn1) | Runs inside whatever keeps Node-RED itself running (service/PM2/Docker) — not specified by the package | No — Maker API polling + webhook receiver | [package README](https://raw.githubusercontent.com/fblackburn1/node-red-contrib-hubitat/main/README.md) |
| PC Controller / EventGhost plugin | Manual unzip into EventGhost's plugin folder; EventGhost's own persistence (a Startup-folder shortcut, per the forum thread's install steps), **not a Windows service** — the thread does not describe installing EventGhost as a service, and does not discuss session/desktop requirements at all | Not documented either way in the thread — EventGhost is a general Windows automation tool that can drive UI/input actions, which historically implies an interactive session, but the linked forum post does not say so explicitly | [Hubitat community forum thread](https://community.hubitat.com/t/release-pc-controller-send-and-receive-commands-to-from-your-windows-pc-eventghost/78640) |
| TTS to Raspberry/Windows via MQTT and Python (forum thread) | Plain script; **no persistence mechanism documented** in the thread | Needs `playsound` audio output, which typically wants an interactive/logged-in session, but the thread does not discuss this or a service option at all | [community forum thread](https://community.hubitat.com/t/tts-to-raspbery-windows-via-mqtt-and-python/43697) |
| HubiThings Replica / Home Assistant Device Bridge | No PC helper — Groovy-only, runs on the hub | N/A | [HubithingsReplica](https://github.com/DaveGut/HubithingsReplica); [HADB forum thread](https://community.hubitat.com/t/release-home-assistant-device-bridge-hadb/67109) |

None of the six real PC-helper integrations found documents a Windows service that also needs to
touch the physical display; the MoonHalo Bridge's requirement (DDC/CI writes to an attached
monitor from a background process) has no same-domain precedent to copy. This table reproduces and
narrows `docs/research/bridge-language-choice.md`'s integration survey to the run-method/desktop
question specifically.

## Comparison of the four methods for this Bridge

| | Windows service (NSSM or native `sc.exe`) | Logon-triggered Scheduled Task | Startup-folder shortcut | (Ruled out) Interactive-service flag |
|---|---|---|---|---|
| **Desktop/display access** | Runs in session 0, non-interactive window station, by Microsoft's documented default — "services use a noninteractive window station and cannot interact with the user" ([Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services)). Whether `EnumDisplayMonitors`/`SetVCPFeature` specifically can still reach an attached physical monitor from here is **not documented** either way (see "Microsoft facts" below) — this is the whole open question | Documented to run *in the user's own logged-on session* when configured as "Run only when user is logged on" (`LogonType` = `TASK_LOGON_INTERACTIVE_TOKEN`, "User must already be logged on. The task will be run only in an existing interactive session," [Principal.LogonType](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype)) — same session as the interactive desktop, so display access is not in question | Runs after interactive sign-in, in the signed-in user's own session — same guarantee as the logon-task interactive case, per Microsoft Support's own description that Startup-folder items launch "when a user signs in" ([Configure Startup applications in Windows](https://support.microsoft.com/en-us/windows/configure-startup-applications-in-windows-115a420a-0bff-4a6f-90e0-1934c844e473)) | An old (pre-Vista) "Allow service to interact with desktop" checkbox is documented as deprecated: "Services cannot directly interact with a user as of Windows Vista. Therefore, the techniques mentioned in the section titled Using an Interactive Service should not be used in new code" ([Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services)) |
| **Starts before logon (survives no one signed in)** | Yes — this is the defining property of a Windows service; it starts at boot regardless of any interactive logon | No — `ONLOGON` "specifies that the task runs whenever a user (any user) logs on" ([schtasks create](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create)); nothing runs before a session exists | No — same limitation; Microsoft Support describes it as launching "when a user signs in," i.e., after sign-in only | N/A |
| **Restarts automatically after a crash** | NSSM: yes, documented — the `AppExit` registry value governs what NSSM does when the managed process exits, and "if the key does not exist in the registry when nssm runs it will create it and set the value to **Restart**" ([nssm.cc/usage](https://nssm.cc/usage)); a native `sc.exe`-created service gets this via `sc failure` / Recovery tab, not surveyed here in detail | Yes, but must be explicitly configured — Task Scheduler's `RestartOnFailure` element takes a `Count` ("the number of times that the Task Scheduler will attempt to restart the task") and an `Interval` ("how long the Task Scheduler will attempt to restart the task," minimum 1 minute, maximum 31 days); "Both child elements must be set" ([RestartOnFailure element](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-restartonfailure-settingstype-element)); `schtasks /create` has no direct flag for this — it requires either `/xml` with a task definition carrying `<RestartOnFailure>`, or a later `schtasks /change`/PowerShell `New-ScheduledTaskSettingsSet -RestartCount -RestartInterval` step | No — not documented anywhere as a Startup-folder feature; a crashed process in the Startup folder simply stays dead until next logon | N/A |
| **Admin rights needed to set up** | Yes — installing any Windows service (NSSM's `nssm install` or `sc.exe create`) requires administrative rights (standard Windows service-control-manager behavior; not specific to NSSM's own docs, which don't restate this) | Yes to *create/view/change* it via `schtasks`, per Microsoft's own stated permission rule: "To schedule, view, and change all tasks on the local computer, you must be a member of the Administrators group" ([schtasks commands, "Required permissions"](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks)) — but the task then *runs* as the ordinary logged-on user (`/ru "%USERNAME%" /rl LIMITED`, the README's own command), not as an elevated process | No — dragging a shortcut into `shell:startup` needs no elevation | N/A |
| **Hidden window** | Yes, inherently — services never show a window | Yes, if the launcher calls `pythonw` (the windowless interpreter) instead of `python`/`py`; the README's `run_bridge.cmd` briefly shows a console window at logon unless edited to call `pythonw` | Same — a shortcut to `pythonw` shows no window; a shortcut to `python`/`py`/a `.cmd` does | N/A |
| **How to stop/remove** | `nssm stop <name>`, `nssm remove <name> confirm` (documented on the Bridge's own README, matching `nssm.cc`'s install/remove command pattern) | `schtasks /run`, `schtasks /query`, `schtasks /delete /tn <name> /f` — all documented on the `schtasks` reference pages above | Delete the shortcut from `shell:startup`; no command-line equivalent documented | N/A |

## Microsoft facts

- **Interactive Services (session 0 isolation, general).** "By default, services use a
  noninteractive window station and cannot interact with the user." "All services run in Terminal
  Services session 0. Therefore, if an interactive service displays a user interface, it is
  visible only to the user who connected to session 0." "Services cannot directly interact with a
  user as of Windows Vista." This page never mentions `EnumDisplayMonitors`, GDI, `HMONITOR`, or
  the Monitor Configuration API — its scope is windows/dialogs/message boxes, not display
  enumeration or DDC/CI. ([Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services))
- **Session Zero Guidelines for UMDF Drivers** (still-live, substantive, though written for a
  different kind of session-0 process — a driver host, not a Win32 service): "As a general rule, a
  UMDF driver can safely call functions that are exported in kernel32.dll, but **not** functions
  exported in user32.dll." `EnumDisplayMonitors` and `GetMonitorInfoW` are user32.dll functions.
  This is the closest documented guidance that names user32 by name in a session-0 context, but it
  is explicitly about UMDF driver hosts, not services generally, so it cannot be read as a direct
  answer for the Bridge. ([Session Zero Guidelines for UMDF Drivers](https://learn.microsoft.com/en-us/windows-hardware/drivers/wdf/session-zero-guidelines-for-umdf-drivers))
- **`EnumDisplayMonitors`/Monitor Configuration API and services/session 0: not documented.** None
  of the function reference pages (`EnumDisplayMonitors`, `GetMonitorInfoW`,
  `GetNumberOfPhysicalMonitorsFromHMONITOR`, `GetPhysicalMonitorsFromHMONITOR`, `SetVCPFeature`,
  `GetVCPFeatureAndVCPFeatureReply`, `GetCapabilitiesStringLength`,
  `CapabilitiesRequestAndCapabilitiesReply`, `DestroyPhysicalMonitors`) mentions services, session
  0, or window stations at all (already established in `docs/research/ddcci-windows-api.md` §8;
  reconfirmed here — no new page found in this pass that contradicts it). A targeted search for
  primary-source evidence of `SetVCPFeature`/DDC-CI succeeding or failing from a Windows service
  found none.
- **Third-party (non-Microsoft-authored, not DDC/CI-specific) empirical evidence that session 0
  gets a degraded display surface exists.** A GitLab Runner maintainer's issue documents measured
  behavior: a process running as a Windows service (tested both as `NT AUTHORITY\LOCAL SYSTEM` and
  as a local user account) was capped at 1024x768 screen resolution, versus the native 1280x800
  achieved "running interactively in session 1" — characterized in the issue as "an intentional
  platform limitation imposed for security reasons." This is about screen *resolution* for
  UI-rendering purposes, not DDC/CI monitor communication, and is not a Microsoft source, but it is
  concrete, checked evidence that session 0 does not simply present the same display environment
  as the interactive session. ([gitlab-runner issue #37955](https://gitlab.com/gitlab-org/gitlab-runner/-/issues/37955))
- **Task Scheduler `schtasks` facts:**
  - Creating/viewing/changing any task on the local computer requires Administrators-group
    membership: "To schedule, view, and change all tasks on the local computer, you must be a
    member of the Administrators group." ([schtasks commands](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks))
  - `/rl <level>`: "Specifies the Run Level for the job. Acceptable values are **LIMITED**
    (scheduled tasks will be ran with the least level of privileges, such as Standard User
    accounts) and **HIGHEST** ... The default value is **Limited**."
  - `/ru {[<domain>]<user> | system}`: "Runs the task with permissions of the specified user
    account. By default, the task runs with the permissions of the current user of the local
    computer, or with the permission of the user specified by the /u parameter, if one is
    included." (Both quotes from [schtasks create](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create).)
  - `ONLOGON`: "Specifies that the task runs whenever a user (any user) logs on. You can specify a
    date, or run the task the next time the user logs on." (same page)
  - Restart-on-failure is not a `schtasks /create` command-line flag; it is the XML
    `<RestartOnFailure>` element with required `<Count>` and `<Interval>` children (see table
    above), settable via `/xml` at creation or `schtasks /change` / PowerShell afterward.
  - **"Run only when user is logged on" vs. "Run whether user is logged on or not" — documented as
    the `LogonType` values on the task's `Principal`.** `TASK_LOGON_INTERACTIVE_TOKEN` (value 3):
    "User must already be logged on. The task will be run only in an existing interactive
    session" — this is "Run only when user is logged on," and it is the one that guarantees the
    interactive desktop/window station. `TASK_LOGON_PASSWORD` (value 1, "use a password for
    logging on the user... password must be supplied at registration time") and
    `TASK_LOGON_S4U` (value 2, "no password is stored... no access to either the network or
    encrypted files") back the "Run whether user is logged on or not" option in the Task Scheduler
    UI — these run without requiring an existing interactive session and are correspondingly
    **not** guaranteed to have desktop/window-station access. ([Principal.LogonType](https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype))
  - `schtasks /create ... /sc onlogon /ru "%USERNAME%" /rl LIMITED` (the Bridge README's own
    command) does not pass `/it`; per the `/it` parameter's own description, a task only gets the
    "interactive-only" `LogonType` when `/it` is explicitly used, or implicitly by virtue of using
    `/ru` with the current session's own credentials at creation time in the older schtasks
    behavior — the safest, most explicit way to guarantee `TASK_LOGON_INTERACTIVE_TOKEN` semantics
    is to add `/it` (documented: "Specifies to run the scheduled task only when the run as user...
    is logged on to the computer") or to build the task from an XML definition with
    `<LogonType>InteractiveToken</LogonType>` directly.
- **Startup folder (`shell:startup`) facts.** Programs are added "by copying or creating a
  shortcut to the app's executable to either" the per-user or common Startup folder (per-user path:
  `%userprofile%\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`); items launch
  "when a user signs in." ([Configure Startup applications in Windows](https://support.microsoft.com/en-us/windows/configure-startup-applications-in-windows-115a420a-0bff-4a6f-90e0-1934c844e473))
  Microsoft's own support page does not itself state the restart-on-crash or pre-logon-start
  limitations; those are inferred from the mechanism (a plain shortcut, launched once at sign-in,
  with no supervising process) rather than quoted from a Microsoft source in this pass — **treat
  "no restart on crash" and "runs after login only" as inference from the documented mechanism, not
  as a directly-quoted Microsoft statement.**
- **NSSM (nssm.cc/usage) facts.**
  - `AppEnvironmentExtra`: "nssm also respects the AppEnvironmentExtra registry value, which should
    have the same format as AppEnvironment. Environment variables set in AppEnvironmentExtra will
    be added to the service's default environment" — supplements rather than replaces the service's
    environment.
  - `AppExit`: governed by `HKLM\System\CurrentControlSet\Services\<servicename>\Parameters\AppExit`;
    "If the key does not exist in the registry when nssm runs it will create it and set the value
    to **Restart**. Change it to either **Ignore** or **Exit** to specify the action taken" —
    restart-on-exit is NSSM's *default* behavior, no extra configuration required (unlike Task
    Scheduler's `RestartOnFailure`, which must be explicitly set).
  - Desktop interaction: the only line found is "If the service runs under the LOCALSYSTEM account
    and is configured to interact with the desktop, you may be able to view the output directly" —
    this points at the same deprecated Windows service "interact with desktop" checkbox described
    (and described as obsolete) on Microsoft's own Interactive Services page above; nssm.cc does
    not document its own session/window-station behavior beyond this one line, and does not state
    whether an NSSM-managed service's session context differs from a native `sc.exe`-created
    service's.

## Recommendation

**Use the logon-triggered Scheduled Task, configured to run only when the user is logged on, as
the Bridge's primary and recommended launch method — not the NSSM service.**

Reasoning:

1. **The one fact that decides this is undocumented for the service path and documented for the
   task path.** Whether a session-0 service can reach the physical display via
   `EnumDisplayMonitors`/the Monitor Configuration API is not stated anywhere in the Microsoft
   Learn pages for those functions (§8 of `ddcci-windows-api.md`, reconfirmed above), and the
   closest adjacent guidance (UMDF session-zero guidelines) advises *against* user32 calls from a
   session-0 process as "a general rule." A logon task set to "Run only when user is logged on" is,
   by contrast, documented in plain language to run "only in an existing interactive session" —
   the exact session the physical monitor is attached to and rendering through.
2. **Third-party evidence, though not about DDC/CI specifically, corroborates the worry rather than
   dispelling it.** The GitLab Runner issue shows Windows deliberately gives session-0 processes a
   different, degraded display surface (a capped virtual resolution) than the interactive session
   gets — consistent with, though not proof of, DDC/CI writes also failing to reach the real
   attached monitor from session 0.
3. **The task path's practical downsides are minor for this deployment.** The Bridge is a
   single-maintainer, single-PC, always-logged-in-when-in-use tool (per `CONTEXT.md`'s definition
   of "Connection state" — offline is expected and handled gracefully when the PC is off); "does
   not start before logon" and "stops at logoff" are non-issues for a laptop the maintainer
   controls and is normally logged into whenever the monitor is in use. The service's biggest
   advantage — running before any interactive logon — is not needed here.
4. **The task path is easy to make resilient and hidden.** `RestartOnFailure` (`Count`/`Interval`)
   gives crash recovery once explicitly configured (via `/xml` or a follow-up `schtasks /change`/
   `New-ScheduledTaskSettingsSet` step — `schtasks /create`'s own flags don't cover it directly),
   and calling `pythonw` instead of `py`/`python` in `run_bridge.cmd` removes the console-window
   flash the README already flags as a known cosmetic issue.
5. **This is consistent with, not a reversal of, the Bridge's existing README and the language-
   choice research.** The README already documents the logon task as the fallback and states the
   NSSM service's session-0 reachability is "unresolved... and must be confirmed by hand";
   `bridge-language-choice.md` independently concludes the session-0 question is
   language-independent, so no implementation change can fix it — only running outside session 0
   can. Promoting the already-written fallback to the primary recommendation does not contradict
   either document; it resolves the "to be confirmed" placeholder in the README's service section
   using facts gathered here, without requiring the empirical test to be run first, since the
   empirical test's only possible favorable outcome (service works) does not carry a lower cost
   than simply using the task, while its unfavorable outcome (service silently fails to move the
   monitor) is the one the README's own troubleshooting table already treats as the likely case.

**Exact commands for the recommended method**, expanding on the README's existing fallback
section:

```
:: Create the task (requires an elevated/Administrator command prompt to CREATE it,
:: even though it will RUN as the ordinary logged-on user):
schtasks /create /tn "MoonHaloBridge" ^
  /tr "\"C:\Users\RBILLC\source\repos\Hubitat\Bridges\BenQ_MoonHalo\run_bridge.cmd\"" ^
  /sc onlogon /ru "%USERNAME%" /rl LIMITED /it

:: Edit run_bridge.cmd to call `pythonw -m moonhalo_bridge serve %*` instead of `py`
:: so no console window appears at logon.

:: Add restart-on-failure (schtasks /create has no direct flag for this; /change
:: does not expose it either -- use an exported/edited XML and /create /xml, or
:: PowerShell's ScheduledTasks module):
$action    = New-ScheduledTaskAction -Execute "C:\Users\RBILLC\source\repos\Hubitat\Bridges\BenQ_MoonHalo\run_bridge.cmd"
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$settings  = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "MoonHaloBridge" -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited

:: Run it once by hand to test, check status, stop/remove:
schtasks /run /tn "MoonHaloBridge"
schtasks /query /tn "MoonHaloBridge" /v
schtasks /delete /tn "MoonHaloBridge" /f
```

The `/it` flag is added relative to the README's current command specifically to make the task's
`LogonType` explicitly `TASK_LOGON_INTERACTIVE_TOKEN` ("interactive-only") rather than leaving it
to schtasks' default inference — this is the documented mechanism that guarantees "Run only when
user is logged on" semantics rather than "Run whether user is logged on or not."

**What would flip this recommendation:** if the Bridge ever needs to run before any interactive
logon (e.g., the PC is meant to answer Hub requests while sitting at the Windows lock screen with
nobody signed in), only a service can do that, and at that point the empirical test the README
already prescribes (start the NSSM service, issue a brightness call, watch the monitor) becomes
mandatory rather than optional — this document does not resolve that question, only the "which
should we default to, and document as recommended" question asked here.

## Open questions

- **Whether the empirical session-0 test would actually succeed is still unknown** — this document
  argues for defaulting to the task *without* running that test, on the grounds that the
  documented facts already tilt against the service and the task's downsides are acceptable for
  this deployment. If a future need for pre-logon startup arises, the test in the Bridge README's
  "Verification steps" section is the only way to actually know, and no source found in this pass
  (Microsoft or third-party) answers it directly for `EnumDisplayMonitors`/`SetVCPFeature`
  specifically.
- **Whether NSSM's managed-service session/window-station context is identical to a native
  `sc.exe`-created service's** is not documented on nssm.cc or found elsewhere in this pass — both
  are assumed to be equally subject to session-0 isolation (both ultimately register as an SCM
  service running under a service account), but this is inference, not a confirmed fact.
  (Previously flagged as open in `docs/research/bridge-language-choice.md` too.)
- **The exact `schtasks /create` behavior around `/it` and implicit `LogonType` inference** was not
  fully pinned down: the `/it` parameter's documented text describes it as restricting the task to
  run "only when the run as user... is logged on," and a verbose query shows `Logon Mode:
  Interactive only` for such a task, but the doc page does not explicitly cross-reference this to
  the COM-level `TASK_LOGON_INTERACTIVE_TOKEN` enum value in the same page — the mapping asserted
  above (`/it` ⇒ `TASK_LOGON_INTERACTIVE_TOKEN`) is inferred from the two pages' consistent
  descriptions of "interactive-only," not from a single page stating the equivalence directly.
- **No Startup-folder-specific Microsoft page was found that states "no restart on crash" or "does
  not run before logon" in so many words** — Microsoft Support's page only describes how to add an
  item and that it runs "when a user signs in." Both limitations claimed in the comparison table
  are inferred from the plain mechanism (an unsupervised shortcut launched once at sign-in) rather
  than quoted.
- **EventGhost/PC Controller's actual desktop requirement is undocumented** in the one forum thread
  read for this project (and for `bridge-language-choice.md`) — EventGhost is capable of
  driving keyboard/mouse/UI automation generally, which usually implies an interactive session, but
  neither this pass nor the earlier one found a primary source saying so for this specific plugin.

---

## Sources consulted

- https://learn.microsoft.com/en-us/windows/win32/services/interactive-services
- https://learn.microsoft.com/en-us/windows-hardware/drivers/wdf/session-zero-guidelines-for-umdf-drivers
- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks
- https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create
- https://learn.microsoft.com/en-us/windows/win32/taskschd/principal-logontype
- https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-restartonfailure-settingstype-element
- https://support.microsoft.com/en-us/windows/configure-startup-applications-in-windows-115a420a-0bff-4a6f-90e0-1934c844e473
- https://nssm.cc/usage
- https://gitlab.com/gitlab-org/gitlab-runner/-/issues/37955
- https://learn.microsoft.com/en-us/answers/questions/210041/low-level-monitor-api (checked; not relevant — about custom DDC/CI byte sequences, not session 0)
- https://learn.microsoft.com/en-us/answers/questions/2156326/why-does-enumdisplaymonitors-still-return-just-dis (checked; not relevant — about disconnected-monitor enumeration in a desktop app, not session 0)
- https://github.com/homebridge/homebridge/wiki/Install-Homebridge-on-Windows-10
- https://github.com/homebridge/homebridge-config-ui-x/wiki/Homebridge-Service-Command
- https://raw.githubusercontent.com/jeubanks/hubitat-mqtt-bridge/master/README.md
- https://raw.githubusercontent.com/fblackburn1/node-red-contrib-hubitat/main/README.md
- https://community.hubitat.com/t/release-pc-controller-send-and-receive-commands-to-from-your-windows-pc-eventghost/78640
- https://community.hubitat.com/t/tts-to-raspbery-windows-via-mqtt-and-python/43697
- https://github.com/DaveGut/HubithingsReplica
- https://community.hubitat.com/t/release-home-assistant-device-bridge-hadb/67109
- `C:\Users\RBILLC\source\repos\Hubitat\CONTEXT.md`
- `C:\Users\RBILLC\source\repos\Hubitat\Bridges\BenQ_MoonHalo\README.md`
- `C:\Users\RBILLC\source\repos\Hubitat\docs\research\bridge-language-choice.md`
- `C:\Users\RBILLC\source\repos\Hubitat\docs\research\ddcci-windows-api.md`
