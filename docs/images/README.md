# Images

Pictures the root README and the forum post draft reference. Keep the file
names: replacing a file under the same name updates every page that shows it.

| File | Shows | Status |
|---|---|---|
| `device-page.png` | The Hub's device page for the MoonHalo: commands, current states, state variables. | Captured 2026-10-09 (Driver 0.0.17, Bridge 0.0.12). |
| `moonhalo-lit.jpg` | A photo of the lit MoonHalo behind the RD280UG. | **Placeholder.** The user's photo. |
| `google-home-device-card.png` | The Google Home app's device card with the white-temperature slider. | **Placeholder.** The user's phone screenshot. |
| `google-home-community-device-type.png` | The Google Home Community app's device-type page for the MoonHalo. | **Placeholder.** The user's hub screenshot. |

The screenshots for the Google Home setup guide (#52) also go in this folder.

## Retaking the device-page screenshot

The device page opens without a login on the LAN. From PowerShell, with the hub's address and the
device id in the URL:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --hide-scrollbars `
  --window-size=1400,1320 --virtual-time-budget=20000 `
  --screenshot="$PWD\docs\images\device-page.png" http://192.168.86.73/device/edit/181
```

The picture shows the device name and LAN addresses, which is accepted. Check that it shows
nothing else private before committing it.
