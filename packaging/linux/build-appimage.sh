#!/usr/bin/env bash
# Wrap dist/rs7 (PyInstaller) into an AppImage. Usage: build-appimage.sh VERSION
# Run the AppImage for the GUI; "<AppImage> cli measure ..." runs the rs7 command.
set -euo pipefail
version=$1
arch=$(uname -m)
root=$(cd "$(dirname "$0")/../.." && pwd)
appdir=$root/build/RS-7.AppDir
rm -rf "$appdir"
mkdir -p "$appdir/usr/lib"
cp -r "$root/dist/rs7" "$appdir/usr/lib/rs7"
cp "$root/packaging/linux/rs7.desktop" "$appdir/rs7.desktop"
cp "$root/packaging/rs7.png" "$appdir/rs7.png"
cat > "$appdir/AppRun" <<'RUN'
#!/bin/sh
here=$(dirname "$(readlink -f "$0")")
if [ "$1" = "cli" ]; then
    shift
    exec "$here/usr/lib/rs7/rs7" "$@"
fi
exec "$here/usr/lib/rs7/rs7-gui" "$@"
RUN
chmod +x "$appdir/AppRun"
if ! command -v appimagetool >/dev/null; then
    curl -fsSL -o /tmp/appimagetool \
        "https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-$arch.AppImage"
    chmod +x /tmp/appimagetool
    appimagetool=/tmp/appimagetool
else
    appimagetool=appimagetool
fi
mkdir -p "$root/dist"
ARCH=$arch APPIMAGE_EXTRACT_AND_RUN=1 "$appimagetool" "$appdir" \
    "$root/dist/gammascientific-rs7-$version-linux-$arch.AppImage"
