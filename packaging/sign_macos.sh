#!/usr/bin/env bash
set -euo pipefail

executable="$1"
: "${APPLE_SIGN_IDENTITY:?APPLE_SIGN_IDENTITY is required}"
: "${APPLE_ID:?APPLE_ID is required}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required}"
: "${APPLE_APP_PASSWORD:?APPLE_APP_PASSWORD is required}"

codesign --force --options runtime --timestamp --sign "$APPLE_SIGN_IDENTITY" "$executable"
codesign --verify --strict --verbose=2 "$executable"
archive="${executable}.notarization.zip"
ditto -c -k --keepParent "$executable" "$archive"
xcrun notarytool submit "$archive" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_PASSWORD" \
  --wait
rm -f "$archive"
