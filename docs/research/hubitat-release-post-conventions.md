# Conventions of a [RELEASE] thread in Custom Apps and Drivers

Researched 2026-10-08 for the BenQ MoonHalo Bridge post. Method: the Discourse JSON API of https://community.hubitat.com (topic JSON, category JSON, search). Labels: [DOC] Hubitat's own text, [STAFF] Hubitat staff post, [FORUM] community post, [INFERENCE] my reasoning.

## 1. The category's stated purpose and rules

- [DOC] The only official text is the category description and the pinned About post (topic 73528, https://community.hubitat.com/t/about-the-custom-apps-and-drivers-category/73528, by staff/admin bobbyD, 2021-05-29): "A place to discuss about favorite apps and drivers developed through the community effort." Both are the same single sentence (post version 2).
- [FORUM] A reply under it (wayne.pirtle, 2021-05-29): "I think the comments you included before your edit were very good guidance. It would help the designer better communicate the value to the rest of the community." The pre-edit text is not retrievable (revisions endpoint refused; post version 2 only). [INFERENCE] bobbyD once wrote guidance about communicating a project's value, then cut it. Nothing official remains.
- [DOC] No written rules were found: no posting restrictions, no required template, no required tag, no mention of HPM or licenses. The category's `topic_template` is empty.
- [INFERENCE] Anyone with a forum account can post. Authors seen are ordinary members (trust level 2 to 3), not staff. Conventions below are community habit, not Hubitat policy.
- [INFERENCE] The pinned About topic is the only pinned topic of 30 on the first listing page, so no pinned "how to post a release" guide exists in this category.
- Search for "Community Developed" tag or similar found nothing relevant (hits were unrelated topics). [INFERENCE] There is no such tag. Tag lists on all sampled release threads were empty.

## 2. Title format

Titles on the first listing page (https://community.hubitat.com/c/comappsanddrivers.json), 2026-10-08:

- [FORUM] `[RELEASE] Muse Bridge v1.1.0` (166673), `[Release] Battery Monitor 2.0` (162329), `[RELEASE] Device Health Monitor` (163229), `[RELEASE] iStore Hot Water Heat Pump App and Driver` (166644), `[Release] Reolink Integration - Cameras, Doorbells, NVRs & Home Hubs` (165352), `[RELEASE] PositionGuard Family Presence - one presence device per family member, area-level, no coordinates on your hub` (165032), `[Release] Envisalink Security (Vista ONLY) - Native Hubitat TPI Driver (No Proxy Required)` (164482), `[RELEASE] ThinQ Connect Integration (Official API) for Hubitat` (156677), `[RELEASE] Hub Information Driver v3` (109902), `[RELEASE] Ecobee Suite, version 1.9.00` (113359), `[RELEASE] OwnTracks for Hubitat Presence Detection` (130821), `[RELEASE] Tuya Temperature Humidity Illuminance LCD Display with a Clock (w/ healthStatus)` (88093), `[RELEASE] Google SDM API - Nest integration` (52226), `[RE-RELEASE] Nexia Thermostat Manager (Trane Home)` (164454), `[Re-release] Hubitat Ring Integration (Unofficial)` (43619), `[PROJECT] Driver for Unifi Protect Controllers` (76759).
- [INFERENCE] Convention: square-bracket prefix `[RELEASE]` (case varies: `[Release]` is common), then product name, then optionally a short descriptor after a dash. Version number in the title is optional and mixed (Muse Bridge v1.1.0, Hub Information Driver v3, Ecobee 1.9.00 have it; Device Health Monitor, Google SDM, OwnTracks, Reolink do not). Long-lived threads (thousands of posts) drop the version because the title cannot keep up; a first release can use `v1.0.0` or omit it.
- [FORUM] Variants: `[RE-RELEASE]` for a revived project, `[PROJECT]` for work in progress, `[Beta RELEASE]` for betas (hpmArchitect, topic 162237, in the Developers category).
- [INFERENCE] A MoonHalo title like `[RELEASE] BenQ MoonHalo Bridge - control a BenQ monitor's MoonHalo backlight` fits the descriptor pattern.

## 3. How updates are announced

- [FORUM] Edit the first post, then add a short reply pointing to it. Battery Monitor (162329): the OP carries release notes by date (2.0, 2.1, 2.8.1 ... 2.8.4) and the author replies "Updates and Corrections made- APP Code updated / See OP notes" (post 16) and "Try the updated link in the OP" (post 11). Device Health Monitor (163229) post 7: "Device Health Monitor v1.2.0 - Now Available! SEE LINK IN OP", then a bullet list of improvements.
- [FORUM] Muse Bridge keeps the version in the OP ("Version 1.1.0 released 10/7/2026") and the thread has one post at the time of reading.
- [INFERENCE] Convention: one thread per product for its whole life; new versions are announced as replies in that thread, with the OP edited to stay current. A new thread is only used for a re-release after abandonment (`[RE-RELEASE]`).

## 4. Structure of a good opening post

Muse Bridge v1.1.0 (https://community.hubitat.com/t/release-muse-bridge-v1-1-0/166673), the closest analogue, about 900 words:

- [FORUM] H1 repeating the title, a one-line tagline ("Talk to your house - and have it talk back."), 2 intro paragraphs, an "In 30 seconds" paragraph, 2 screenshots with a caption, then 3 more short paragraphs (standalone use, MIT licensed, author motivation), the version/date line, and the support disclaimer.
- [FORUM] Then H2 sections: Features (bulleted, 7 bullets), Code (GitHub repo link plus latest release link), Installation (manual, HPM, Updating), Alert rule examples, Device health, Donations. 6 H2 headings in total.
- [FORUM] Support line, verbatim: "This app is a "community app" and is not supported by Hubitat. Contact @rayzurbock for support. Use at your own risk."
- [FORUM] Reolink (165352): one-line pitch, GitHub link, then H3s: Why I built this, Features, Installation (HPM and Manual), Setup, Device compatibility (table of tested models with status icons), Known limitations, Testers wanted. 7 H3 headings.
- [FORUM] PositionGuard (165032): no headings; bold run-in labels ("How it works", "Install"), 2 screenshots, closing "Status: v1.0.0, open source ... I'd genuinely like to hear what breaks" and "Support: GitHub Issues and Discussions on the repo - or right here, I'll be in the thread." Signed with first name.
- [FORUM] iStore (166644): about 200 words; H2s Features, Hubitat Package Manager Installation, Configure; "More info in the Github repo"; ends "Testers and feedback welcome".
- [FORUM] Battery Monitor (162329): a credit line to earlier authors, dated release notes, a numbered Setup Guide and Tips in plain text, no headings. Weaker structure; its first replies were about a broken GitHub link.
- [INFERENCE] Common sections: pitch, screenshots, features, installation (manual and HPM), GitHub link, support/feedback call, version/date. Changelog lives in the OP only on small projects (Battery Monitor); Muse Bridge and Reolink leave it to GitHub releases. Known limitations and tested hardware are valued where hardware varies (Reolink).
- Length: [FORUM] 200 to 900 words; 5 to 12 paragraphs of prose plus bullet lists; 0 to 7 headings; 1 to 3 screenshots.

## 5. Raw import URLs versus the repo

- [FORUM] Both. Muse Bridge gives the repo link, the releases link, and, in the install steps, a raw URL to paste into Apps Code > New App > Import: `https://raw.githubusercontent.com/rayzurbock/hubitat-muse-bridge/main/apps/muse-bridge.groovy`. Reolink lists one raw URL per file (two drivers, one app). TRIGGERcmd (22715, 2019) linked the GitHub blob pages.
- [FORUM] Updating: Muse Bridge says "Apps Code -> select Muse Bridge -> Import -> paste the code URL -> Save, or update through HPM".
- [FORUM] A broken or private repo link is the most common first complaint (Battery Monitor posts 3 to 25: GitHub error page, then "Try the updated link in the OP", then "the code won't show", then raw code showed up). [INFERENCE] Test every link while logged out before posting; prefer a raw URL for code and the repo URL for docs.

## 6. Hubitat Package Manager

- [FORUM] Mentioned in most recent release threads, never required. Muse Bridge lists "Hubitat Package Manager support" as a feature but installs manually first, and says "Search for Muse Bridge in Hubitat Package Manager and install; (coming soon upon approval; timestamp 10/7/2026)". Reolink and iStore give HPM first, manual second.
- [FORUM] Regulars ask for it: Battery Monitor post 12 "Are you planning on putting it in HPM?", answer "I have not gotten that far ... Not even sure of the process for HPM", reply from dnickel pointing to the hpmArchitect manifest builder (https://community.hubitat.com/t/beta-release-building-hpm-manifests-with-hpmarchitect/162237). Later the OP says "Battery Monitor 2.0 is available in the HPM" with thanks to csteele.
- [FORUM] A user thread (https://community.hubitat.com/t/102487) says HPM "got orphaned recently when the original developer moved on" and package updates are sparse. [INFERENCE] HPM is expected by regulars but optional; saying "HPM submission pending" is acceptable.

## 7. Presenting a PC-side companion program

- [FORUM] Muse Bridge is, despite its name, a Hubitat app that talks to a cloud assistant; there is no PC-side program. It is not an example of a PC bridge. Its handling of an outside service: link to the service (muse.ai), say what you hand it (cloud API URL and token), say it "works standalone" without it.
- [FORUM] Closest real example: TRIGGERcmd for Hubitat (https://community.hubitat.com/t/22715, 2019, 5 posts, auto-closed after 365 days). OP order: what the PC utility does, use cases, credit to the original author, pricing ("For one PC/Mac/Linux machine its free"), a numbered "Installing TRIGGERcmd" with one download link per OS (Windows, Linux RPM/DEB, Mac), then the Hubitat app and driver as GitHub links, then a worked example with a `.bat` snippet. Both the Groovy header (Apache 2.0, copyright, "Updated for Hubitat Elevation by Royski") and the driver `importUrl` carry attribution.
- [FORUM] First replies there were a trust question: "leary of unknown agents running on my internal systems", "cloud based which gives me shivers allowing any cloud service ... full and complete access to my PC", and "Why not do this with EventGhost which is local?" Answer given: only triggers are passed, not commands.
- [INFERENCE] For MoonHalo, a section "What runs on the PC" should state: Windows version, Python version, how to install and start the bridge (service or startup task), port and LAN exposure, that it only accepts commands from the hub, that nothing leaves the LAN, and what it changes on the monitor (DDC/CI VCP writes). This pre-empts the TRIGGERcmd-style objection.
- [INFERENCE] A Server-on-Docker precedent exists in the category (`[GUIDE] Echo Speaks Server on Docker (or without)`, topic 111186) but was not read.

## 8. License and author attribution

- [FORUM] Muse Bridge: "MIT licensed." in the body, plus a Donations section (Cash App, Venmo, PayPal). Contact name by @mention in the support disclaimer.
- [FORUM] PositionGuard: "open source", signed "- Christer". iStore: HPM instruction "Select the one authored by Jamie Curnow" (the HPM author name disambiguates among packages).
- [FORUM] Battery Monitor: "Expanded on the already great app by Brandon Gordon and larry kahn." Credit for prior work goes in the first line.
- [INFERENCE] License is stated in one clause in the OP and in the repo; no thread quotes a full license text. The MoonHalo repo already uses MIT (LICENSE.txt, holder Rothenberg Industries, LLC), so "MIT licensed" plus the author name is enough.
- No thread mentions a "Community Developed" tag. The only equivalent is the phrase "community app ... not supported by Hubitat" in the Muse Bridge support line. [INFERENCE] Copy that disclaimer style; it is a convention of this one author, not a rule.

## 9. What first replies ask for

- [FORUM] Link and install problems first (Battery Monitor: GitHub error page, code not showing).
- [FORUM] "Are you planning on putting it in HPM?" (Battery Monitor post 12).
- [FORUM] Compatibility questions about other models and setups (Reolink post 3: user's phone app lacks the HTTP/ONVIF settings; PositionGuard post 3: multiple hubs and locations).
- [FORUM] Feature requests (Battery Monitor: on-screen report button; Device Health Monitor: sortable columns, per-protocol scan interval).
- [FORUM] Trust and privacy of anything that runs outside the hub or in the cloud (TRIGGERcmd; PositionGuard pre-empts it with a "Privacy, concretely" paragraph and "It does depend on the PositionGuard hosted service").
- [FORUM] Alternatives: "Why not do this with EventGhost?"; a dstutz reply disputing a side claim in the pitch (MAC randomization). [INFERENCE] Avoid unverifiable side claims.
- [STAFF] The only staff-flag reply in the sampled threads is marktheknife (moderator) in Reolink post 5, answering a how-to question with a concrete path through the vendor's iOS app. No staff post stated category rules, and no staff reply policed format. The auto-closer "system" account (staff flag) closes threads 365 days after the last reply.
- [INFERENCE] Pre-empt in the OP: tested monitor model(s) (RD280UG only) and whether other BenQ or DDC/CI monitors might work; Windows version; what the hub needs to reach (IP and port); security and LAN scope; HPM status; how to report bugs (GitHub Issues and the thread); what happens when the PC sleeps or the monitor is in standby.

## Sources read

- https://community.hubitat.com/t/73528.json (About), /t/166673.json (Muse Bridge, 1 post), /t/162329.json (Battery Monitor, first 20 of 509 posts), plus openings and early replies of /t/165352, /t/165032, /t/166644, /t/163229, /t/22715; listing from /c/comappsanddrivers.json.
- Not read: remaining 489 Battery Monitor posts, and the other listed release threads beyond their titles.

## Template

```
Title: [RELEASE] <Product name> <vX.Y.Z optional> - <short descriptor>

# <Product name>
<One-line tagline.>

<Paragraph 1: what it does and for whom.>
<Paragraph 2: the two parts: Hubitat driver on the hub, <bridge> on a <OS> PC; why a bridge is needed.>
<Screenshot(s) of the device page / dashboard tile> <caption>

Version <X.Y.Z> released <date>. <MIT licensed.> <Support disclaimer: community driver, not supported by Hubitat; contact @<forum name>.>

## Features
- <attribute / command>
- <health attribute: unknown / online / offline>
- <...>

## Requirements
- Hubitat hub, firmware <version tested>
- <OS and version> PC on the same LAN, <Python version>
- <Monitor model(s) tested>; <what other hardware may work>
- <Port the hub must reach; firewall note>

## Installation
### 1. Bridge on the PC
1. <Download / clone link>
2. <Install steps>
3. <Run as service / startup task>
4. <How to verify it is up>

### 2. Driver on the hub
1. Drivers Code > New Driver > Import > <raw URL> > Import > Save
2. Devices > Add Device > Virtual > Type <driver name>
3. Set <bridge IP>, <port>; Save Preferences

### Hubitat Package Manager
<Available / submission pending / not yet.>

### Updating
<Driver: re-import the raw URL. Bridge: <steps>.>

## What runs on the PC
<What the bridge does, what it listens on, who can call it, what it changes on the monitor, that nothing leaves the LAN.>

## Known limitations
- <...>

## Links
- GitHub: <repo URL>
- Releases / changelog: <URL>
- Issues: <URL>

## Feedback
<Testers wanted: other monitor models, Windows versions. Report here or on GitHub Issues.>

-- <name>
```
