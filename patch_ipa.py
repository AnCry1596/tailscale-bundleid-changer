#!/usr/bin/env python3
"""
patch_ipa.py
  1. Unzip IPA
  2. Remove iOS-16+ extensions (widgets etc.)
  3. Patch ALL bundle ID references in every Info.plist
  4. Inject Bypass.dylib via LC_LOAD_DYLIB (optool or insert_dylib)
  5. Rezip → ready for TrollStore
"""

import os
import sys
import shutil
import zipfile
import plistlib
import argparse
import subprocess
from pathlib import Path

# ── plist keys that carry bundle IDs ─────────────────────────────────────────
BUNDLE_ID_KEYS = [
    "CFBundleIdentifier",
    "WKAppBundleIdentifier",
    "WKCompanionAppBundleIdentifier",
    "NSExtension.NSExtensionAttributes.WKAppBundleIdentifier",
]

# Extensions to always remove (require iOS 16+ or cause crashes)
DEFAULT_REMOVE_PLUGINS = [
    "IPN-Widgets.appex",
    "IPN-iOS-Extension.appex",
    "IPN-tvOS-Extension.appex",
    "IPN-macOS-Extension.appex",
]

# ── helpers ───────────────────────────────────────────────────────────────────

def find_app_dir(payload_dir: Path) -> Path:
    apps = list(payload_dir.glob("*.app"))
    if not apps:
        raise FileNotFoundError("No .app bundle found inside Payload/")
    return apps[0]


def replace_in_value(value, old: str, new: str):
    """Recursively replace old bundle ID prefix inside plist value."""
    if isinstance(value, str):
        if value == old:
            return new
        if value.startswith(old + "."):
            return new + value[len(old):]
        return value
    if isinstance(value, dict):
        return {k: replace_in_value(v, old, new) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_in_value(i, old, new) for i in value]
    return value


def patch_plist(plist_path: Path, old_id: str, new_id: str) -> bool:
    try:
        with open(plist_path, "rb") as f:
            plist = plistlib.load(f)
    except Exception as e:
        print(f"  [warn] could not read {plist_path.name}: {e}")
        return False

    patched = replace_in_value(plist, old_id, new_id)
    if patched == plist:
        return False

    with open(plist_path, "wb") as f:
        plistlib.dump(patched, f, fmt=plistlib.FMT_XML)
    print(f"  [patched] {plist_path}")
    return True


def inject_dylib(binary_path: Path, dylib_dest_path: str, tool: str):
    """
    Inject dylib load command into Mach-O binary.
    tool: path to 'optool' or 'insert_dylib'
    """
    if not Path(tool).exists() and shutil.which(tool) is None:
        print(f"  [warn] injection tool not found: {tool} — skipping dylib injection")
        return False

    tool_name = Path(tool).stem
    if tool_name == "optool":
        cmd = [tool, "install", "-c", "load", "-p", dylib_dest_path, "-t", str(binary_path)]
    else:  # insert_dylib
        cmd = [tool, "--inplace", "--all-yes", dylib_dest_path, str(binary_path)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [error] dylib injection failed:\n{result.stderr}")
        return False
    print(f"  [injected] {dylib_dest_path} → {binary_path.name}")
    return True


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Patch Tailscale IPA for TrollStore")
    parser.add_argument("ipa", help="Path to input .ipa")
    parser.add_argument("--new-id", default="annnekkk.modified.tailscale",
                        help="New bundle ID (default: annnekkk.modified.tailscale)")
    parser.add_argument("--dylib", default="",
                        help="Path to Bypass.dylib to inject (skip if not provided)")
    parser.add_argument("--inject-tool", default="optool",
                        help="Injection tool binary: optool or insert_dylib (default: optool)")
    parser.add_argument("--keep-plugins", action="store_true",
                        help="Do not remove any PlugIns (keep all extensions)")
    parser.add_argument("--output", default="",
                        help="Output .ipa path (default: <stem>_patched.ipa)")
    args = parser.parse_args()

    ipa_path = Path(args.ipa).resolve()
    if not ipa_path.exists():
        sys.exit(f"Error: IPA not found: {ipa_path}")

    out_path = Path(args.output).resolve() if args.output else \
               ipa_path.with_name(ipa_path.stem + "_patched.ipa")

    work_dir = ipa_path.parent / "_ipa_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir()

    # ── 1. Extract ────────────────────────────────────────────────────────────
    print(f"\n[1/5] Extracting {ipa_path.name} ...")
    with zipfile.ZipFile(ipa_path, "r") as zf:
        zf.extractall(work_dir)

    payload_dir = work_dir / "Payload"
    app_dir = find_app_dir(payload_dir)
    print(f"      App bundle : {app_dir.name}")

    main_plist_path = app_dir / "Info.plist"
    with open(main_plist_path, "rb") as f:
        main_plist = plistlib.load(f)
    old_id = main_plist["CFBundleIdentifier"]
    new_id = args.new_id
    print(f"      Old bundle ID: {old_id}")
    print(f"      New bundle ID: {new_id}")

    # ── 2. Remove iOS-16+ plugins ─────────────────────────────────────────────
    plugins_dir = app_dir / "PlugIns"
    if not args.keep_plugins and plugins_dir.exists():
        print(f"\n[2/5] Removing incompatible PlugIns ...")
        for name in DEFAULT_REMOVE_PLUGINS:
            p = plugins_dir / name
            if p.exists():
                shutil.rmtree(p)
                print(f"  [removed] {name}")
    else:
        print(f"\n[2/5] Skipping plugin removal.")

    # ── 3. Patch all Info.plists ──────────────────────────────────────────────
    print(f"\n[3/5] Patching Info.plist files ...")
    for plist_path in app_dir.rglob("Info.plist"):
        patch_plist(plist_path, old_id, new_id)

    # Also patch any embedded .plist files that might reference the bundle ID
    for plist_path in app_dir.rglob("*.plist"):
        if plist_path.name != "Info.plist":
            patch_plist(plist_path, old_id, new_id)

    # ── 4. Inject dylib ───────────────────────────────────────────────────────
    print(f"\n[4/5] Dylib injection ...")
    if args.dylib:
        dylib_src = Path(args.dylib).resolve()
        if not dylib_src.exists():
            print(f"  [warn] dylib not found at {dylib_src} — skipping injection")
        else:
            # Copy dylib into app bundle
            dylib_dest = app_dir / "Frameworks" / dylib_src.name
            dylib_dest.parent.mkdir(exist_ok=True)
            shutil.copy2(dylib_src, dylib_dest)
            print(f"  [copied] {dylib_src.name} → Frameworks/")

            # The @rpath load path TrollStore will see
            dylib_load_path = f"@executable_path/Frameworks/{dylib_src.name}"

            # Find main executable
            exe_name = main_plist.get("CFBundleExecutable", app_dir.stem)
            exe_path = app_dir / exe_name
            if not exe_path.exists():
                print(f"  [warn] executable not found: {exe_path}")
            else:
                inject_dylib(exe_path, dylib_load_path, args.inject_tool)
    else:
        print("  [skip] no --dylib provided")

    # ── 5. Rezip ──────────────────────────────────────────────────────────────
    print(f"\n[5/5] Repacking IPA ...")
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(work_dir.rglob("*")):
            if file_path.is_file():
                arcname = file_path.relative_to(work_dir)
                # Preserve executable permission via external_attr
                zi = zipfile.ZipInfo(str(arcname))
                zi.compress_type = zipfile.ZIP_DEFLATED
                st = file_path.stat()
                zi.external_attr = (st.st_mode & 0xFFFF) << 16
                with open(file_path, "rb") as f:
                    zf.writestr(zi, f.read())

    shutil.rmtree(work_dir)

    print(f"\nDone! → {out_path}")
    print("Transfer to device and open with TrollStore.")

if __name__ == "__main__":
    main()
