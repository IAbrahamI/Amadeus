#!/usr/bin/env python3
"""The app icon in every size every system needs, made from its SVG sources in core/desktop-tauri/icons/src/. Change
the icon there, run this once, and commit what it writes; the builds use these files as they are.

  amadeus-icon.svg            the master (Apple grid): 48 px and up
  amadeus-icon-small.svg      hand-tuned for 32 px and below (thicker, no ring)
  amadeus-icon-fullbleed.svg  edge to edge: Android's legacy icons, the Play Store, Apple's touch icon
  android/ic_launcher_*.svg   Android's adaptive icon layers (108 dp, art inside the 66 dp safe zone) and its themed layer
  android/ic_notify.svg       the white notification icon

Needs rsvg-convert (librsvg) and ImageMagick's magick. Run from anywhere:  python3 packaging/icons.py"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "core", "desktop-tauri", "icons", "src")
ICONS = os.path.join(ROOT, "core", "desktop-tauri", "icons")
WEB = os.path.join(ROOT, "core", "web")
RES = os.path.join(ROOT, "android", "app", "src", "main", "res")
DENSITIES = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
SMALL_UP_TO = 32


def svg(name):
    return os.path.join(SRC, name)


def render(source, size, out):
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), "-o", out, source], check=True)
    return out


def app_icon(size, out):
    """The right source for the size: the hand-tuned small one up to 32 px, the master above."""
    return render(svg("amadeus-icon-small.svg" if size <= SMALL_UP_TO else "amadeus-icon.svg"), size, out)


def icns(sizes, out):
    """A Mac .icns with every slot macOS asks for, each one a PNG (16 and 32 hand-tuned)."""
    slots = [("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512), ("ic10", 1024),
             ("ic11", 32), ("ic12", 64), ("ic13", 256), ("ic14", 512)]
    body = b""
    for kind, px in slots:
        data = open(sizes[px], "rb").read()
        body += kind.encode() + struct.pack(">I", len(data) + 8) + data
    with open(out, "wb") as f:
        f.write(b"icns" + struct.pack(">I", len(body) + 8) + body)


def main():
    for tool in ("rsvg-convert", "magick"):
        if not shutil.which(tool):
            sys.exit(f"Needs {tool}.")
    tmp = tempfile.mkdtemp(prefix="amadeus-icons-")
    sizes = {px: app_icon(px, os.path.join(tmp, f"{px}.png")) for px in (16, 24, 32, 48, 64, 128, 256, 512, 1024)}

    # the desktop app (Tauri: Mac, Windows, Linux)
    shutil.copy(sizes[1024], os.path.join(ICONS, "icon.png"))
    shutil.copy(sizes[32], os.path.join(ICONS, "32x32.png"))
    shutil.copy(sizes[128], os.path.join(ICONS, "128x128.png"))
    shutil.copy(sizes[256], os.path.join(ICONS, "128x128@2x.png"))
    subprocess.run(["magick", *(sizes[px] for px in (16, 24, 32, 48, 64, 256)), os.path.join(ICONS, "icon.ico")], check=True)
    icns(sizes, os.path.join(ICONS, "icon.icns"))

    # the dashboard and the phone's web pages
    shutil.copy(svg("amadeus-icon.svg"), os.path.join(WEB, "app-icon.svg"))
    shutil.copy(sizes[32], os.path.join(WEB, "app-icon-32.png"))
    for px in (192, 512):
        app_icon(px, os.path.join(WEB, f"app-icon-{px}.png"))
    render(svg("amadeus-icon-fullbleed.svg"), 180, os.path.join(WEB, "app-icon-180.png"))  # Apple rounds it itself
    render(svg("amadeus-icon-fullbleed.svg"), 512, os.path.join(WEB, "app-icon-maskable-512.png"))  # a phone crops it to its shape

    # the phone app: adaptive layers (108 dp), the legacy icon (48 dp), the notification icon (24 dp)
    for name, k in DENSITIES.items():
        d = os.path.join(RES, f"mipmap-{name}")
        for layer in ("foreground", "background", "monochrome"):
            render(svg(f"android/ic_launcher_{layer}.svg"), round(108 * k), os.path.join(d, f"ic_launcher_{layer}.png"))
        render(svg("amadeus-icon-fullbleed.svg"), round(48 * k), os.path.join(d, "ic_launcher.png"))
        render(svg("android/ic_notify.svg"), round(24 * k), os.path.join(RES, f"drawable-{name}", "ic_notify.png"))
    render(svg("amadeus-icon-fullbleed.svg"), 512, os.path.join(ROOT, "android", "app", "src", "main", "ic_launcher-playstore.png"))
    shutil.rmtree(tmp)
    print("Icons written from", SRC)


if __name__ == "__main__":
    main()
