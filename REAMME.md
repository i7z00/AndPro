# AndPro.py

Automates CA certificate installation for **Caido** or **Burp Suite** on an Android virtual device (AVD). Covers both the user-store (manual finish) and the full system-store (fully automated) installation flows.

---

## Requirements

| Tool | Purpose | How to get it |
|---|---|---|
| `Python 3.8+` | Run the script | [python.org](https://www.python.org/downloads/) |
| `adb` | Communicate with the emulator | Android SDK → `platform-tools` → add to PATH |
| `openssl` | Compute cert hash; DER→PEM conversion (Burp) | Linux: pre-installed · Windows: [Git for Windows](https://git-scm.com/download/win) or [Win32 OpenSSL](https://slproweb.com/products/Win32OpenSSL.html) |
| `emulator` | Launch AVD with writable system | Android SDK → `emulator` dir → add to PATH |
| **Proxy running** | Source of the CA cert | Caido or Burp Suite must be listening on `127.0.0.1:8080` |

> **No pip installs needed** — the script uses Python's standard library only.

---

## AVD Requirements (system-store mode)

- **Image type:** `Google APIs` — **NOT** `Google Play Store` (Play Store images block root)
- **API level:** ≤ 33
- **Architecture:** x86 / x86_64 recommended for speed

Create one in Android Studio: `Device Manager → Create Device → pick a release without the Play Store icon`.

---

## Usage

### Caido — user-store
```bash
python AndPro.py --proxy caido --user-store
```
Sets up `adb reverse`, pushes `ca.crt` to `/sdcard`, then prints the remaining on-device steps.

### Caido — system-store (fully automated)
```bash
python AndPro.py --proxy caido --system-store --avd Pixel_6_API_33
```

### Burp Suite — user-store
```bash
python AndPro.py --proxy burp --user-store
```
Downloads `cacert.der` from Burp, converts it to PEM, pushes to `/sdcard`.

### Burp Suite — system-store (fully automated)
```bash
python AndPro.py --proxy burp --system-store --avd Pixel_6_API_33
```

### Optional flags
| Flag | Default | Description |
|---|---|---|
| `--caido-host` | `127.0.0.1` | Host where the proxy is listening |
| `--caido-port` | `8080` | Port where the proxy is listening |
| `--device` | auto | ADB serial — auto-detected when only one device is connected |
| `--avd` | — | AVD name from `emulator -list-avds` (required for `--system-store`) |

```bash
# Custom port, specific device:
python AndPro.py --proxy burp --system-store \
  --avd Pixel_6_API_33 --caido-port 8080 --device emulator-5554
```

---

## Troubleshooting

### `avbctl disable-verification` fails — `Error writing to partition 'vbmeta'`
**Cause:** The AVD is using a **Google Play Store** system image, or the emulator was not launched with `-writable-system`.

**Fix:**
1. In Android Studio Device Manager, delete the current AVD.
2. Create a new AVD — on the system image screen, choose a **Google APIs** image (no Play Store icon) at API ≤ 33.
3. Re-run the script.

### `adb remount` fails — `Skipping /system` / `Read-only file system`
**Cause:** `avbctl disable-verification` did not run or did not succeed before remount.

**Fix:** The script already enforces the correct order. If you see this error, it means `avbctl` silently failed — re-check the AVD image type (see above).

### Traffic not appearing in proxy history
- Disable **Mobile data** on the emulator (Settings → Network → Mobile data off).
- Disable any VPN connections inside the emulator.
- If `adb reverse` was set before the emulator fully booted, re-run:
  ```bash
  adb -s <device-id> reverse tcp:8080 tcp:8080
  ```
- Try setting the Wi-Fi proxy hostname to `10.0.2.2` instead of `127.0.0.1` on the device.

### `emulator` / `adb` / `openssl` not found
Add the relevant Android SDK directories to your system PATH:

**Windows (PowerShell — run once):**
```powershell
$sdk = "$env:LOCALAPPDATA\Android\Sdk"
[Environment]::SetEnvironmentVariable(
  "Path",
  "$env:Path;$sdk\platform-tools;$sdk\emulator",
  "User"
)
```

**Linux / macOS (`~/.bashrc` or `~/.zshrc`):**
```bash
export ANDROID_SDK=$HOME/Android/Sdk
export PATH=$PATH:$ANDROID_SDK/platform-tools:$ANDROID_SDK/emulator
```

### Burp: cert download returns an HTML page instead of a cert
Burp's `/cert` endpoint only works when the proxy listener is active. Confirm:
- Burp → **Proxy → Proxy settings → Proxy listeners** → listener on `127.0.0.1:8080` is running.
- Try opening `http://127.0.0.1:8080/cert` in a desktop browser first — if it downloads a file, the script will work.

---

## How the legacy hash works

Android's system certificate store expects each cert file to be named `<hash>.0` where `<hash>` is the MD5-based "legacy" subject hash computed by:

```bash
openssl x509 -inform PEM -subject_hash_old -in ca.crt
```

The script runs this automatically and renames the file before pushing it to the device.

---

## File structure

```
AndPro.py   Main script — no other files needed
README.md               This file
```

---

## Tested on

| Host OS | Android API | Image type | Proxy |
|---|---|---|---|
| Windows 11 | 33 | Google APIs x86_64 | Caido, Burp |
| Ubuntu 22.04 | 33 | Google APIs x86_64 | Caido, Burp |
| Windows 11 | 30 | Google APIs x86_64 | Caido, Burp |
