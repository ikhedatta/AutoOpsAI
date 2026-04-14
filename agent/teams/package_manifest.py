"""
Package the Teams app manifest into a .zip for upload to Teams Admin Center.

Usage:
    python -m agent.teams.package_manifest

Requires:
    - Replace {{TEAMS_APP_ID}} in manifest.json with your actual App ID
    - Place color.png (192x192) and outline.png (32x32) in the manifest/ folder
"""

import json
import re
import sys
import zipfile
from pathlib import Path

MANIFEST_DIR = Path(__file__).parent / "manifest"
OUTPUT_ZIP = Path(__file__).parent / "autoops-teams-app.zip"

PLACEHOLDER = "{{TEAMS_APP_ID}}"


def validate_and_package(app_id: str | None = None) -> Path:
    manifest_path = MANIFEST_DIR / "manifest.json"
    color_icon = MANIFEST_DIR / "color.png"
    outline_icon = MANIFEST_DIR / "outline.png"

    if not manifest_path.exists():
        sys.exit(f"ERROR: {manifest_path} not found")
    if not color_icon.exists():
        sys.exit(f"ERROR: {color_icon} not found — add a 192x192 PNG icon")
    if not outline_icon.exists():
        sys.exit(f"ERROR: {outline_icon} not found — add a 32x32 PNG icon")

    manifest_text = manifest_path.read_text()

    # Substitute App ID
    if PLACEHOLDER in manifest_text:
        if not app_id:
            sys.exit(
                f"ERROR: manifest.json contains {PLACEHOLDER}. "
                "Pass your App ID as argument: python -m agent.teams.package_manifest <APP_ID>"
            )
        # Validate GUID format
        guid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        if not re.match(guid_pattern, app_id.lower()):
            sys.exit(f"ERROR: '{app_id}' is not a valid GUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)")
        manifest_text = manifest_text.replace(PLACEHOLDER, app_id)

    # Validate JSON
    try:
        manifest_data = json.loads(manifest_text)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: invalid JSON in manifest — {e}")

    # Basic schema checks
    required_fields = ["$schema", "manifestVersion", "version", "id", "bots", "name", "description"]
    for field in required_fields:
        if field not in manifest_data:
            sys.exit(f"ERROR: manifest.json missing required field '{field}'")

    # Package
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_text)
        zf.write(color_icon, "color.png")
        zf.write(outline_icon, "outline.png")

    print(f"✅ Teams app package created: {OUTPUT_ZIP}")
    print(f"   Manifest version: {manifest_data['version']}")
    print(f"   Bot ID: {manifest_data['id']}")
    print(f"\nNext steps:")
    print(f"  1. Go to Teams Admin Center → Manage apps → Upload new app")
    print(f"  2. Upload {OUTPUT_ZIP.name}")
    print(f"  3. Assign the app to users/teams or publish to your org store")
    return OUTPUT_ZIP


if __name__ == "__main__":
    aid = sys.argv[1] if len(sys.argv) > 1 else None
    validate_and_package(aid)
