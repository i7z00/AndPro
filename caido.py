#!/usr/bin/env python3
"""
caido_cert_install.py  –  v2
─────────────────────────────
Automates Caido CA certificate installation on an Android virtual device.

Covers both Caido tutorials:
  • Proxying Browser Traffic  (user-store install + adb reverse)
  • System Partition install  (writable-system emulator flow)

Works on Windows and Linux.  No third-party packages required.

Requirements
────────────
  • Python 3.8+
  • adb        on PATH  (Android SDK / platform-tools)
  • openssl    on PATH  (Linux: pre-installed | Windows: Git-Bash or Win32 OpenSSL)
  • emulator   on PATH  (Android SDK / emulator – system-store mode only)
  • Caido running on localhost:8080  (or pass --caido-host / --caido-port)

Usage
─────
  # User-store (push to /sdcard, set adb reverse, print manual steps):
  python caido_cert_install.py --user-store

  # System-store (fully automated, AVD must be API <= 33, non-Play-Store image):
  python caido_cert_install.py --system-store --avd <avd-name>

  # Optional flags:
  python caido_cert_install.py --system-store --avd Pixel_6_API_33 \
      --caido-host 127.0.0.1 --caido-port 8080 --device emulator-5554

Known limitations
─────────────────
  --system-store only works on emulators that allow root (AOSP / Google APIs images,
  NOT Google Play Store images).  API level must be <= 33.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


# ── ANSI colour helpers ───────────────────────────────────────────────────────

BOLD   = "\033[1m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
RESET  = "\033[0m"


def _color_ok():
    if platform.system() == "Windows":
        return "WT_SESSION" in os.environ or os.environ.get("TERM_PROGRAM") is not None
    return sys.stdout.isatty()


USE_COLOR = _color_ok()


def _c(color, text):
    return f"{color}{text}{RESET}" if USE_COLOR else text


def info(msg):  print(_c(CYAN,   f"[*] {msg}"))
def ok(msg):    print(_c(GREEN,  f"[+] {msg}"))
def warn(msg):  print(_c(YELLOW, f"[!] {msg}"))
def fail(msg):  print(_c(RED,    f"[-] {msg}"), file=sys.stderr)
def step(n, total, msg): print(_c(CYAN, f"\n  [{n}/{total}] ") + msg)


def die(msg):
    fail(msg)
    sys.exit(1)


def header(title):
    bar = "─" * 58
    print(_c(BOLD, f"\n{bar}\n  {title}\n{bar}"))


# ── Tool discovery ────────────────────────────────────────────────────────────

def which(name):
    p = shutil.which(name)
    if p:
        return p
    is_win = platform.system() == "Windows"
    hints = {
        "adb":      "Add Android SDK/platform-tools to PATH.",
        "openssl":  ("Install Git for Windows (includes openssl):\n"
                     "    https://slproweb.com/products/Win32OpenSSL.html"
                     if is_win else
                     "sudo apt install openssl  /  sudo dnf install openssl"),
        "emulator": "Add Android SDK/emulator directory to PATH.",
    }
    die(f"'{name}' not found on PATH.\n  Hint: {hints.get(name, 'Install it and retry.')}")


# ── Shell / adb wrappers ──────────────────────────────────────────────────────

def run(cmd, *, check=True, capture=False, **kw):
    display = " ".join(str(c) for c in cmd)
    info(f"$ {display}")
    result = subprocess.run(cmd, text=True, capture_output=capture, **kw)
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        fail(f"Command failed (exit {result.returncode}): {display}")
        if err:
            print(f"\n  {err}\n", file=sys.stderr)
        sys.exit(1)
    return result


def adb(device, *args, check=True, capture=False):
    return run([which("adb"), "-s", device] + list(args),
               check=check, capture=capture)


def adb_global(*args, check=True, capture=False):
    return run([which("adb")] + list(args), check=check, capture=capture)


# ── Device helpers ────────────────────────────────────────────────────────────

def connected_devices():
    result = adb_global("devices", capture=True)
    serials = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def pick_device(requested):
    devices = connected_devices()
    if not devices:
        die("No Android devices found.  Is the emulator running?")
    if requested:
        if requested not in devices:
            die(f"Device '{requested}' not found.  Connected: {devices}")
        return requested
    if len(devices) == 1:
        ok(f"Auto-selected device: {devices[0]}")
        return devices[0]
    print("\nMultiple devices found:")
    for i, d in enumerate(devices):
        print(f"  [{i}] {d}")
    while True:
        try:
            return devices[int(input("  Select index: ").strip())]
        except (ValueError, IndexError):
            warn("Invalid selection.")


def wait_for_boot(device, timeout_s=180):
    info("Waiting for device to finish booting…")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = adb(device, "shell", "getprop", "sys.boot_completed",
                check=False, capture=True)
        if r.stdout.strip() == "1":
            ok("Device booted.")
            return
        time.sleep(3)
    die("Timed out waiting for boot.")


# ── Certificate helpers ───────────────────────────────────────────────────────

def download_cert(host, port, dest):
    url = f"http://{host}:{port}/ca.crt"
    info(f"Downloading Caido CA certificate from {url}")
    try:
        urllib.request.urlretrieve(url, str(dest))
    except Exception as exc:
        die(f"Download failed: {exc}\n"
            f"  Make sure Caido is running at http://{host}:{port}")
    ok(f"Certificate saved to: {dest}")


def legacy_hash(cert):
    """Return the OpenSSL legacy subject-hash Android's system store expects."""
    result = run(
        [which("openssl"), "x509", "-inform", "PEM", "-subject_hash_old",
         "-in", str(cert)],
        capture=True,
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("-----"):
            return line
    die("Could not extract legacy hash from openssl output.")


# ── Flows ─────────────────────────────────────────────────────────────────────

def user_store_flow(device, host, port):
    """Tutorial 1: adb reverse + push cert to /sdcard."""
    header("User-Store Flow")
    TOTAL = 3

    step(1, TOTAL, "Verify device connectivity")
    adb(device, "shell", "echo", "ok")

    step(2, TOTAL, "adb reverse tcp:8080 tcp:8080")
    adb(device, "reverse", "tcp:8080", "tcp:8080")
    ok("Port forwarding active.")

    step(3, TOTAL, "Push CA certificate to /sdcard/ca.crt")
    with tempfile.TemporaryDirectory() as tmp:
        cert = Path(tmp) / "ca.crt"
        download_cert(host, port, cert)
        adb(device, "push", str(cert), "/sdcard/ca.crt")
    ok("ca.crt is on the device at /sdcard/ca.crt")

    print()
    print(_c(YELLOW,
        "  ┌─ Manual steps required on the device ──────────────────────────┐\n"
        "  │  1. Chrome → http://127.0.0.1:8080/ca.crt → Download          │\n"
        "  │  2. Settings → 'Install a certificate' → CA Certificate        │\n"
        "  │     → Install anyway → pick ca.crt                             │\n"
        "  │  3. Verify: Settings → Trusted credentials → User tab → Caido  │\n"
        "  └────────────────────────────────────────────────────────────────┘"
    ))


def system_store_flow(avd, device_hint, host, port):
    """
    Tutorial 2: System Partition Install.

    Correct operation order (avbctl MUST come before remount):
      1.  Download cert + compute legacy hash
      2.  Kill running emulators
      3.  Launch emulator -writable-system -no-snapshot
      4.  Boot + adb root
      5.  avbctl disable-verification      <-- must be BEFORE remount
      6.  adb reboot
      7.  Boot + adb root (again)
      8.  adb remount                      <-- works now that AVB is disabled
      9.  adb push <hash>.0
      10. adb shell chmod 664
      11. adb reboot
      12. adb reverse tcp:8080 tcp:8080
    """
    header("System-Store Flow")
    TOTAL = 12
    adb_bin = which("adb")
    emu_bin = which("emulator")

    # ── 1. Download + rename ──────────────────────────────────────────────────
    step(1, TOTAL, "Download CA certificate and compute legacy hash")
    workdir = Path(tempfile.mkdtemp(prefix="caido_"))
    cert_src = workdir / "ca.crt"
    download_cert(host, port, cert_src)

    cert_hash = legacy_hash(cert_src)
    ok(f"Legacy hash: {cert_hash}")
    cert_final = workdir / f"{cert_hash}.0"
    cert_src.rename(cert_final)
    ok(f"Certificate renamed to: {cert_final.name}")

    # ── 2. Kill running emulators ─────────────────────────────────────────────
    step(2, TOTAL, "Kill any running emulator  (-writable-system needs a cold boot)")
    running = connected_devices()
    if running:
        warn(f"Running device(s): {running}")
        ans = input("  Kill them now? [Y/n]: ").strip().lower()
        if ans not in ("n", "no"):
            for dev in running:
                run([adb_bin, "-s", dev, "emu", "kill"], check=False)
            time.sleep(4)
            ok("Emulator(s) terminated.")
        else:
            warn("Continuing without kill – /system may stay read-only.")

    # ── 3. Launch emulator ────────────────────────────────────────────────────
    step(3, TOTAL,
         f"Launch AVD '{avd}' with -writable-system -no-snapshot")
    warn("This can take 60-120 s.  Do not touch the emulator window.")
    emu_proc = subprocess.Popen(
        [emu_bin, "-avd", avd, "-writable-system", "-no-snapshot"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ok(f"Emulator started (PID {emu_proc.pid}).")

    # ── 4. Boot + root ────────────────────────────────────────────────────────
    step(4, TOTAL, "Wait for boot then gain root")
    run([adb_bin, "wait-for-device"])
    time.sleep(5)
    device = pick_device(device_hint)
    wait_for_boot(device)
    adb(device, "root")
    time.sleep(3)

    # ── 5. Disable AVB (BEFORE remount) ──────────────────────────────────────
    step(5, TOTAL, "Disable AVB verification  (avbctl disable-verification)")
    warn("avbctl MUST succeed before remount.  "
         "If it fails, see the error message for fixes.")
    r = adb(device, "shell", "avbctl", "disable-verification",
            check=False, capture=True)
    if r.returncode != 0:
        fail("avbctl disable-verification failed:")
        print((r.stdout or r.stderr).strip(), file=sys.stderr)
        print()
        print(_c(YELLOW, "  Root cause & fixes:"))
        print("  • Most common: your AVD uses a 'Google Play' system image.")
        print("    Play Store images block root entirely.  Switch to a")
        print("    'Google APIs' image (no Play Store icon) with API <= 33.")
        print("  • Re-create the AVD in Android Studio with the correct image,")
        print("    then wipe its data before re-running this script.")
        shutil.rmtree(workdir, ignore_errors=True)
        sys.exit(1)
    ok("AVB verification disabled.")

    # ── 6. Reboot ─────────────────────────────────────────────────────────────
    step(6, TOTAL, "Reboot to apply AVB change")
    adb(device, "reboot")
    time.sleep(5)

    # ── 7. Boot + re-root ─────────────────────────────────────────────────────
    step(7, TOTAL, "Wait for reboot then re-gain root")
    run([adb_bin, "wait-for-device"])
    time.sleep(5)
    device = pick_device(device_hint)
    wait_for_boot(device)
    adb(device, "root")
    time.sleep(3)

    # ── 8. Remount ────────────────────────────────────────────────────────────
    step(8, TOTAL, "Remount /system as read-write  (adb remount)")
    adb(device, "remount")
    time.sleep(2)
    ok("/system is now writable.")

    # ── 9. Push cert ──────────────────────────────────────────────────────────
    # cert_final is an ABSOLUTE path so it works regardless of cwd
    step(9, TOTAL, f"Push {cert_final.name} to /system/etc/security/cacerts/")
    adb(device, "push", str(cert_final), "/system/etc/security/cacerts/")
    ok("Certificate pushed.")

    # ── 10. Fix permissions ───────────────────────────────────────────────────
    step(10, TOTAL, "Set permissions: chmod 664")
    remote = f"/system/etc/security/cacerts/{cert_final.name}"
    adb(device, "shell", "chmod", "664", "-v", remote)
    ok("Permissions set.")

    # ── 11. Final reboot ──────────────────────────────────────────────────────
    step(11, TOTAL, "Final reboot")
    adb(device, "reboot")
    time.sleep(5)
    run([adb_bin, "wait-for-device"])
    time.sleep(5)
    device = pick_device(device_hint)
    wait_for_boot(device)
    ok("Device rebooted.")

    # ── 12. adb reverse ───────────────────────────────────────────────────────
    step(12, TOTAL, "Set up adb reverse tcp:8080 tcp:8080")
    adb(device, "reverse", "tcp:8080", "tcp:8080")
    ok("Traffic forwarding active.")

    shutil.rmtree(workdir, ignore_errors=True)

    print()
    ok(_c(BOLD, "System-store installation complete!"))
    print(_c(YELLOW,
        "  ┌─ Verify ──────────────────────────────────────────────────────┐\n"
        "  │  Settings → search 'Trusted credentials'                      │\n"
        "  │  → System tab → find 'Caido'                                  │\n"
        "  └───────────────────────────────────────────────────────────────┘"
    ))


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="caido_cert_install.py",
        description="Install Caido's CA certificate on an Android virtual device.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--user-store",   action="store_true",
                      help="Push cert to /sdcard + set adb reverse + print manual steps.")
    mode.add_argument("--system-store", action="store_true",
                      help="Full system-partition install (requires --avd, API <= 33).")
    p.add_argument("--avd",        metavar="NAME",
                   help="AVD name (required for --system-store).")
    p.add_argument("--device",     metavar="SERIAL",
                   help="ADB serial. Auto-detected when only one device is connected.")
    p.add_argument("--caido-host", metavar="HOST", default="127.0.0.1",
                   help="Caido host (default: 127.0.0.1).")
    p.add_argument("--caido-port", metavar="PORT", default=8080, type=int,
                   help="Caido port (default: 8080).")
    return p


def main():
    args = build_parser().parse_args()

    if args.system_store and not args.avd:
        die("--system-store requires --avd <AVD_NAME>")

    print(_c(BOLD, "\n  Caido Android Certificate Installer  v2"))
    print("  " + "─" * 40)
    print(f"  Mode    : {'system-store' if args.system_store else 'user-store'}")
    print(f"  Caido   : http://{args.caido_host}:{args.caido_port}/ca.crt")
    if args.avd:    print(f"  AVD     : {args.avd}")
    if args.device: print(f"  Device  : {args.device}")
    print()

    if args.user_store:
        user_store_flow(pick_device(args.device), args.caido_host, args.caido_port)
    else:
        system_store_flow(args.avd, args.device, args.caido_host, args.caido_port)


if __name__ == "__main__":
    main()