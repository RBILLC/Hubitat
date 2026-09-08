# Plan: MoonHalo 1.0.0 release

Ticket: [#38](https://github.com/RBILLC/Hubitat/issues/38). Written 2026-09-08 late evening so the next
session can pick this up without the conversation that produced it. Update it as steps close.

## Where things stand (2026-09-08, 23:30)

- The MoonHalo effort under map #1 is complete: specs #13 and #30 and tickets #31-#37 are closed, and
  `feature/benq-moonhalo` was merged to `main` as 6718af7. `main` is the branch to work on now.
- On the hub: Driver **0.0.11** (importUrl serves it from `main`), preference **Default transition (ms)**
  at its default 300. On the PC: Bridge **0.0.6** running from the `MoonHaloBridge` logon scheduled
  task with `config.json` `transition_seconds` 0.3; the Bridge announces 192.168.86.115:5000 to the hub
  at 192.168.86.73.
- The pace that looked best on the real halo, judged by the user: writes back-to-back at the monitor's
  ~60 ms bus pace with fewer steps for a shorter sweep. 0.3 s (six of the nine steps) read as smooth;
  spacing writes 80 ms apart read as stepping. This is why the default is 0.3 and why a Sweep time
  below 0.54 s drops steps rather than slowing (amendment 2 on #30).
- Glossary: `CONTEXT.md` (Transition, Ramp, Sweep time, Target state, Applied state). The Bridge's
  timing rules live in one place, `Pacing.schedule` in `moonhalo_bridge/model.py`.

## Step 1: morning hub test

What to exercise on the hub with Driver 0.0.11 at the 300 ms default, watching the halo:

- A short slider move (two or three steps): should finish in well under a quarter second.
- A full slider sweep and off/on from the device page: six writes, about 0.3 s each, no flash on relight.
- A Google Home voice command and slider (they send setLevel then on): one move, no stutter.
- A rule or Maker API call with a rate, for example `setLevel(20, 3)`: still takes 3 s (explicit rate
  is total time and wins over the preference).
- Change the preference (240 gives five writes, 120 gives three, 0 snaps) and confirm the next command
  changes pace with nothing touched on the PC.

How to read what happened: `Bridges/BenQ_MoonHalo/bridge.log` has one line per request with
`transition=<planned seconds>s steps=<writes>` and a `ramp complete ... elapsed=` line per Ramp.
`py tools/ramp_probe.py brightness` (from `Bridges/BenQ_MoonHalo`, Bridge idle) prints every write with
its timing against the real monitor.

Operating notes learned this session:

- Restart the Bridge after any Bridge code or config change:
  `Stop-ScheduledTask -TaskName MoonHaloBridge; Start-ScheduledTask -TaskName MoonHaloBridge`, then
  `curl http://localhost:5000/health` and check the version. `Invoke-RestMethod` against the Bridge
  hangs from PowerShell; use curl.
- Driving the Bridge from the PC with curl (`/moonhalo/brightness/100?sweep=0.3` and so on) is the
  quickest way to compare paces; loopback is allowed by the access policy.
- A Hubitat `decimal` preference with `range: "0..60"` would not accept values under 1.0 on the device
  page; that is why the preference is whole milliseconds on a `number` input (research note, section 11
  of `docs/research/hubitat-driver-facilities.md`).

## Step 2: code clean-up before announcing

- Driver comments: the user wants them terse, like classic Hubitat drivers (one or two lines per method,
  short header bullets). The 0.0.10 and 0.0.11 comments are; the older header "Behaviour" bullets and the
  `on()`, `setBridgeAddress`, announcement and purge comments are still long. Move anything worth keeping
  into the Bridge README or `model.py` docstrings, which is where explanations live.
- Glossary sweep: "duration" appears in `model.py` (Transition and Pacing docstrings), `http.py` and the
  Bridge README although `CONTEXT.md` lists it under Transition's avoid list; "Pacing" is used throughout
  the Bridge with no glossary entry. Either add the entries or reword.
- `.gitignore`: the `tools/probe_state.json` pattern did not match `Bridges/BenQ_MoonHalo/tools/` (fixed
  alongside this plan); confirm the file no longer shows as untracked.
- Versions: Driver header says "1.0.0 on public announcement". Bump the Driver to 1.0.0 with a changelog
  line, the Bridge `__version__` to 1.0.0, the README `/health` example, and the Driver's "Version" line;
  restart the Bridge task and re-import the Driver on the hub.
- Review pass with `/code-review` against `main` before the bump; run `py -m unittest` from
  `Bridges/BenQ_MoonHalo` (289 tests as of tonight).

## Step 3: Hubitat community post

- Draft it in `docs/forum/` like the existing `google-home-colorsetting-request.md` (status line, suggested
  category, then the post). Category: **Custom Apps and Drivers** (the Google Home post targets Feedback).
- Content: what it is (BenQ RD280UG MoonHalo as a CT bulb through a small Python Bridge on the PC, DDC/CI
  over the Windows Monitor Configuration API, no third-party executable), how to install (import URL,
  Bridge README), what it does (on/off, level, colour temperature, transitions with a Sweep time, Google
  Home through the community integration since the built-in one gives CT-only devices no temperature
  control), known limits (ten brightness levels and seven colour steps in hardware; Windows only; the
  Bridge must run in the logged-on session because of session 0).
- Link the raw Driver URL and `Bridges/BenQ_MoonHalo/README.md`. The user posts it.

## Step 4: GitHub page clean-up

- The root `README.md` is the landing page: keep the driver list, install steps, the full preference list
  (including **Default transition (ms)**) and the pointer to the Bridge README. Check it against the
  Driver's actual preferences after the clean-up.
- Repository description and topics (hubitat, benq, ddc-ci, moonhalo) if not set.
- Confirm `docs/research/` and `docs/forum/` read as reference material, and that nothing refers to the
  dropped ControlMyMonitor approach as current.

## Step 5: website update

- The user maintains a website outside this repo; the content should match the forum post. Ask the user
  for the site and what it currently says about the MoonHalo before drafting.

## After this plan

- #26, Matter light from the PC, is the only other open issue and starts a new wayfinder round.
