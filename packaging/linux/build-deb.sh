#!/usr/bin/env bash
# Wrap dist/rs7 (PyInstaller) into a .deb. Usage: build-deb.sh VERSION
set -euo pipefail
version=$1
arch=$(dpkg --print-architecture)
root=$(cd "$(dirname "$0")/../.." && pwd)
pkg=$root/build/deb
rm -rf "$pkg"
mkdir -p "$pkg/DEBIAN" "$pkg/opt" "$pkg/usr/bin" "$pkg/usr/share/applications" \
    "$pkg/usr/share/icons/hicolor/256x256/apps"
cp -r "$root/dist/rs7" "$pkg/opt/rs7"
ln -s /opt/rs7/rs7 "$pkg/usr/bin/rs7"
ln -s /opt/rs7/rs7-gui "$pkg/usr/bin/rs7-gui"
cp "$root/packaging/linux/rs7.desktop" "$pkg/usr/share/applications/rs7.desktop"
cp "$root/packaging/rs7.png" "$pkg/usr/share/icons/hicolor/256x256/apps/rs7.png"
cat > "$pkg/DEBIAN/control" <<CTL
Package: gammascientific-rs7
Version: $version
Section: science
Priority: optional
Architecture: $arch
Maintainer: phili-b <noreply@users.noreply.github.com>
Homepage: https://github.com/phili-b/gammascientific-rs7
Description: Control software for the Gamma Scientific SpectralLED RS-7
 Command line (rs7) and desktop GUI (rs7-gui) for the RS-7 light source.
 Add yourself to the dialout group to access the serial port:
 sudo usermod -aG dialout \$USER
CTL
mkdir -p "$root/dist"
dpkg-deb --root-owner-group --build "$pkg" "$root/dist/gammascientific-rs7_${version}_$arch.deb"
