# README reference examples for a Hubitat driver with a PC-side companion

Research pass, 2026-10-08, for the root README of "BenQ MoonHalo Bridge" (the landing page a
Hubitat forum [RELEASE] thread links). Labels: [DOC] spec text, [EXAMPLE] observed README,
[INFERENCE] my reasoning. Pages were read through a summarising fetcher, so section lists are
faithful but lengths are approximate.

## Caveats on sources

- echo-speaks-server's repo README is a single H1 line (no other content). echo-speaks' own README
  is about 10 lines and defers everything to a docs site. The real content is at
  tonesto7.github.io/echo-speaks-docs, which I read as a stand-in (it is a site, not a README).
- kkossev/Hubitat has no per-driver README reachable at the one URL I tried (404); his per-driver
  pages are repos in their own right, not read here.
- mbudnek's default branch is `master`; the `main` raw URL 404s. Read through the repo page.

## [DOC] standard-readme spec (RichardLitt/standard-readme, spec.md)

Order: Title, Banner (opt), Badges (opt), Short Description, Long Description (opt), Table of
Contents, Security (opt), Background (opt), Install, Usage, Extra Sections (opt), API (opt),
Maintainer(s) (opt), Thanks (opt), Contributing, License (last).

- Required: Title, Short Description, Table of Contents, Install, Usage, Contributing, License.
- TOC optional under 100 lines. Install/Usage optional for documentation-only repos.
- Short Description under 120 characters, own line, must match the GitHub repo description.
- Title must match the repo/package name, or the mismatch is explained in the Long Description.
- Install must contain a code block; unusual or manual dependencies go in a Dependencies subsection.
- Usage must contain a code block of common use.
- Contributing states where to ask questions, whether PRs are accepted, requirements.
- License gives SPDX id or name and the owner, and is the last section.
- Maintainer(s) needs at least one contact method.
- No broken links.

[INFERENCE] The spec is written for libraries. "Install" and "Usage" map onto our two-sided
install and the device page. Two-sided install needs Dependencies (Python, Maker API) spelled
out. Nothing in it addresses versions, changelog, or a companion service.

## [EXAMPLE] mbudnek/google-home-hubitat-community

- Order: title/intro; Installation (Installing the Hubitat App; Creating the Google smart home
  Action); Configuring Devices (Defining a Device Type, Device Type Settings, about 26 trait
  subsections); Global Settings (PIN codes, Home Graph support).
- Length: very long, roughly 4,000 words, mostly trait reference.
- Leads with product ("Community Maintained Google Home Integration"), not the repo.
- Screenshots: none.
- Requirements: not a section; scattered through the install steps (hub with Apps Code and OAuth,
  Google account, Actions console, optional Cloud service account).
- Install order: hub app first (paste code, enable OAuth, note Client ID/secret), then the external
  Google side, then link the account, then define devices. Numbered, one action per step.
- Versions/changelog: none in the README; a `packageManifest.json` carries the version for HPM.
- License GPL-3.0 (sidebar only); support: GitHub Issues with a template, no support section.
- Good: install is strictly ordered and states which side each step is on; optional features
  (PINs, Home Graph) are fenced off as optional. Bad: no requirements list, no screenshots for a
  three-platform setup, typos and a copy-pasted section (Lock/Unlock repeats Arm/Disarm text),
  unconfirmed items left in the text.

## [EXAMPLE] tonesto7/echo-speaks and echo-speaks-server

- echo-speaks README: logo, H2 "Welcome to Echo Speaks", H4 "Description", a Links line
  (Documentation, Donations). About 10 lines, no screenshot beyond the logo, no requirements,
  install, versions, license, or security text.
- echo-speaks-server README: one H1 and nothing else. The repo has a SECURITY.md and Dockerfile,
  but the README does not point to them.
- Docs site (stand-in): nav Home, Install, Configuration, Updates, Actions, Support, Device API,
  Donations. Home = About, Getting Started, Recent Changes (links CHANGELOG.md; shows version
  4.1.4.0 apps/drivers and 2.7.0 server, last update 2021-04-12). Install = Install Types, then
  Automated (HPM) and Manual (app, driver). Support = Server Removal/Reset, Common Errors,
  Reporting Issues, FAQ.
- Requirements: Hub with web portal access; a free Heroku account. No explicit hub-versus-server
  install sequence; the code-link list is just a list.
- Trust: the only statement is a recommendation to enable Amazon two-factor authentication. The
  server handles Amazon cookies, and nothing says what it stores or where it runs.
- Split: README as signpost, docs site as manual, two repos for two components, version numbers
  tracked separately for apps and server.
- Good: separate version streams; Support page with Common Errors; Update section. Bad: both
  READMEs are empty shells; a user landing from GitHub gets no requirements, no security
  statement, no install order. [INFERENCE] This is the pattern to avoid for a landing page.

## [EXAMPLE] dcmeglio/hubitat-packagemanager

- Order: repo-moved banner; overview; Initial Configuration; Installing a Package; Modifying;
  Repairing; Uninstalling; Updating; Match Up; View Apps and Drivers; Settings; Developer
  Information (Package Manifest with example and commands; Repository File with categories,
  publishing, example).
- Length: long, about 160 lines of prose plus JSON examples. Task-oriented (one section per user
  action), not feature-oriented.
- Leads with a repo-moved notice, then product (a bad lead: reader cannot tell which source is
  current). 11 screenshots, one per task, placed under the section they illustrate.
- Requirements: a hub; hub-security credentials if enabled; stated inside Initial Configuration,
  no requirements heading.
- Changelog: none in README; manifest `releaseNotes` field is empty in the example. SemVer advice
  for developers only. No license or support section; discussion thread link only.
- Good: warnings placed where the mistake happens (do not uninstall manually, cannot be undone,
  avoid the 3 am maintenance window); explains the limit of Match Up. Bad: stale banner,
  copy-pasted Repair text and wrong image alt text, inconsistent dates, no license.

## [EXAMPLE] kkossev/Hubitat

- Order: H1 "My Hubitat Elevation drivers and apps"; community profile and donation line; a driver
  list (bullet per driver: linked name, one-line description, forum thread); an H4 for third-party
  drivers he supports; "Branch policy".
- Length: short list page, about 50 lines. Leads with the author, then a catalogue.
- Screenshots: none. Install steps: none (points to CONTRIBUTING.md and PUBLISHING.md).
- Versions: tags for immutable versions; `development` is canonical, `main` kept for old links
  and HPM; both `repository.json` must match. No changelog on the page.
- License: none. Support: forum threads per driver plus GitHub.
- Good: each driver links to its forum thread (the support channel is the thread); branch policy
  is explicit. Bad: status labels mixed into entries (W.I.P., obsolete), an empty bullet, heading
  levels skipped, branch policy aimed at maintainers sits where users look.
- [INFERENCE] It is a catalogue, not a product page. Useful only for the forum-thread-per-driver
  habit, which suits our [RELEASE] thread link.

## [EXAMPLE] arnbme/apcupsd (my choice: hub plus Windows service)

Why: it is a Hubitat driver whose job depends on a program on a Windows PC (apcupsd plus VBS
scripts) and it is a real forum-supported project. I found no Node/Python bridge README for
Hubitat on GitHub; the search turned up general driver collections only.

- Order (18 sections): Purpose, Requirements, Features, Support, Installation Overview, Modules,
  Virtual Device, Testing, Scheduled Task, EventGhost, Power Settings, RM Rules, Restarts, UPS
  Wiring, Uninstalling, Help, Known Issues.
- Leads with product (one sentence: Windows PC running apcupsd sends UPS events to the hub so it
  shuts down gracefully). Three screenshots, all Rule Machine rules.
- Requirements are their own early section (hub on a UPS outlet, cable to a Windows USB port,
  apcupsd installed). Support is an early section (forum thread, direct message, donation).
- Install order interleaves sides and labels each step: Windows, Hub, Windows, Hub, Hub, Both,
  Windows, Both. Includes Testing, Uninstalling, Known Issues.
- No version, changelog, or license. Credits the original driver author.
- Good: requirements and support up front; explicit Testing and Uninstalling; Known Issues
  stated honestly; credit and alternatives linked. Bad: 18 sections is a wall, numbering and file
  counts disagree with the text, steps repeated, no license or version.

## Cross-cutting findings [INFERENCE]

1. Every good README leads with one sentence on what the product does for the user. The
   packagemanager banner and the kkossev profile line are the leads to avoid.
2. Requirements are a heading only in apcupsd. Elsewhere they hide inside steps. A forum reader
   decides in ten seconds; a short Requirements list serves that.
3. Where there are two components, the one worth copying is apcupsd's habit of tagging each install
   step with its side (hub or PC), plus mbudnek's numbered, one-action steps. Echo Speaks shows the
   cost of omitting an order.
4. Trust is stated almost nowhere. A bridge that accepts HTTP commands and writes to a monitor is
   a thing a stranger wants to understand: who can call it, on what network, what it logs. Echo
   Speaks (cookies) has no statement; our Bridge README has an allowlist that the root README does
   not mention. [DOC] standard-readme gives this an optional Security section before Install.
5. Version history lives outside the README in every case (CHANGELOG.md, manifest, tags). The
   root README should state the current Driver and Bridge versions and link out.
6. Support is the forum thread everywhere that has one; GitHub Issues is secondary.
7. Screenshots appear only in task-per-section READMEs and in apcupsd. A device page screenshot
   fits our preferences section; none of the examples has one for a device page.
8. License appears in a README in none of the examples (sidebar only). The spec requires it as the
   last section; the repo has LICENSE.txt, so a one-line section costs nothing.

## (a) Recommended section order for this repo's root README

1. Title and one-line description (under 120 characters; also the GitHub repo description) -
   "BenQ MoonHalo Bridge: control the MoonHalo backlight of a BenQ RD280UG monitor from Hubitat."
2. What it is - three or four sentences: the Driver on the Hub, the Bridge on the PC, the
   Hub-to-Bridge HTTP direction, what you get (dimmable, color-temperature light; Google Home).
   A diagram or device-page screenshot goes here.
3. Requirements - hub, PC (Windows, Python version, monitor over DDC/CI with the model), network
   (same LAN), Maker API for announcements, Hubitat Package Manager optional.
4. Install - numbered, each step tagged Hub or PC, ordered so the first success is visible:
   (1) PC: install and start the Bridge (link the Bridge README for the detail), (2) Hub: import
   the Driver, (3) Hub: add the virtual device and set preferences, (4) test: switch on, set a
   level, confirm `bridgeLink` online. Include import URL and a code block.
5. Usage - what the device does, commands, brightness and color temperature behaviour, and the
   Google Home notes (shortened; detail in a linked doc).
6. Configuration reference - preferences table, attributes and state variables (the current
   README's bulk, moved below Usage and made a table).
7. Security and trust - what the Bridge listens on, allowlist, no internet exposure, what it
   writes to the PC and logs.
8. Troubleshooting and known limits - link the Bridge README table; offline behaviour, seven
   colour steps.
9. Versions and changelog - current Driver and Bridge versions, compatibility pair (Driver needs
   Bridge 0.0.9 or later), link to the changelog or release notes.
10. Other drivers in this repo - the Tuya soil sensor, one line each. Last of the content because
    it is not the subject of the [RELEASE] thread.
11. Support - the forum [RELEASE] thread first, GitHub Issues second.
12. License - SPDX id and owner; the file is LICENSE.txt.

## (b) Three worst gaps in the current README

1. No opening that says what the product is, who it is for, or what it needs. The first lines
   describe the repo as a collection ("custom drivers and their companion bridges"); a forum
   reader gets no requirements and no install order. The Bridge install appears only as a link
   after the driver steps, so the install order is hub-only.
2. Reference material outranks the install. About 80 lines of preferences, attributes and state
   variables sit before any statement of how the pieces connect; the "Installing a driver" steps
   are generic and the MoonHalo has no end-to-end first-run check.
3. No versions, support, license, or trust sections. The README names no current version or
   compatibility pair beyond a mid-paragraph note, no forum thread or Issues link, no license
   mention, and no statement of what the Bridge exposes on the LAN, although LICENSE.txt and an
   allowlist already exist.
