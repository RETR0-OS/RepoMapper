#!/usr/bin/env bash
set -euo pipefail

bundle="$1"
: "${APPLE_SIGN_IDENTITY:?APPLE_SIGN_IDENTITY is required}"
: "${APPLE_ID:?APPLE_ID is required}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required}"
: "${APPLE_APP_PASSWORD:?APPLE_APP_PASSWORD is required}"

executable="$bundle/hydra-graph"
if [[ ! -f "$executable" ]]; then
  echo "Managed service executable is missing: $executable" >&2
  exit 1
fi

# Sign every Mach-O payload deepest-first, then verify the launcher. PyInstaller
# one-directory builds include extension modules and libraries beside the main
# executable; notarizing only the launcher leaves an incomplete trust chain.
while IFS= read -r file_path; do
  if file -b "$file_path" | grep -q "Mach-O"; then
    codesign --force --options runtime --timestamp --sign "$APPLE_SIGN_IDENTITY" "$file_path"
  fi
done < <(find "$bundle" -type f -print | awk '{ print length, $0 }' | sort -rn | cut -d' ' -f2-)

codesign --verify --deep --strict --verbose=2 "$executable"
archive="${bundle}.notarization.zip"
ditto -c -k --keepParent "$bundle" "$archive"
xcrun notarytool submit "$archive" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_PASSWORD" \
  --wait
rm -f "$archive"
