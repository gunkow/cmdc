#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/dist/cmdc.app"
DEST="/Applications/cmdc.app"

echo "==> Building cmdc.app..."

# 1. Ensure dependencies and editable install
cd "$ROOT"
uv sync
PYTHON_HOME="$(uv run python -c 'import sys; print(sys.base_prefix)')"
PYTHON_DYLIB="$(uv run python -c 'import sys, sysconfig; from pathlib import Path; framework = sysconfig.get_config_var("PYTHONFRAMEWORK"); print(Path(sys.base_prefix) / "Python" if framework else Path(sysconfig.get_config_var("LIBDIR")) / sysconfig.get_config_var("LDLIBRARY"))')"
SITE_PACKAGES="$(uv run python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
STDLIB="$(uv run python -c 'import sysconfig; print(sysconfig.get_path("stdlib"))')"

# 2. Prepare bundle directories
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 3. Generate icon if needed
ICON_PATH="$ROOT/assets/AppIcon.icns"
if [ ! -f "$ICON_PATH" ]; then
    mkdir -p "$ROOT/assets"
    echo "==> Generating AppIcon.icns..."
    uv run python - << 'EOF'
import os
from AppKit import (
    NSImage, NSBitmapImageRep, NSGraphicsContext,
    NSColor, NSBezierPath, NSString, NSFont,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSParagraphStyleAttributeName, NSMutableParagraphStyle, NSCenterTextAlignment,
    NSPNGFileType, NSShadow, NSGradient
)
from Foundation import NSMakeRect, NSMakeSize

def create_icon_png(size, path):
    img = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    img.lockFocus()
    ctx = NSGraphicsContext.currentContext()
    ctx.setImageInterpolation_(3)

    pad = size * 0.08
    rect = NSMakeRect(pad, pad, size - 2*pad, size - 2*pad)
    corner = size * 0.224

    bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, corner, corner)

    col1 = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.08, 0.10, 0.16, 1.0)
    col2 = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.20, 0.30, 1.0)
    grad = NSGradient.alloc().initWithStartingColor_endingColor_(col2, col1)
    grad.drawInBezierPath_angle_(bg_path, -90.0)

    border_col = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.35, 0.55, 0.95, 0.6)
    border_col.setStroke()
    bg_path.setLineWidth_(max(1.0, size * 0.02))
    bg_path.stroke()

    font_size = size * 0.44
    font = NSFont.systemFontOfSize_weight_(font_size, 0.6)
    para = NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(NSCenterTextAlignment)

    shadow = NSShadow.alloc().init()
    shadow.setShadowColor_(NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.6, 1.0, 0.5))
    shadow.setShadowOffset_(NSMakeSize(0, -size * 0.02))
    shadow.setShadowBlurRadius_(size * 0.06)

    attrs = {
        NSFontAttributeName: font,
        NSForegroundColorAttributeName: NSColor.colorWithCalibratedRed_green_blue_alpha_(0.96, 0.97, 1.0, 1.0),
        NSParagraphStyleAttributeName: para,
    }
    
    text = NSString.stringWithString_("⌘C")
    str_size = text.sizeWithAttributes_(attrs)
    text_rect = NSMakeRect(0, (size - str_size.height) / 2.0 - size * 0.01, size, str_size.height)
    
    shadow.set()
    text.drawInRect_withAttributes_(text_rect, attrs)

    img.unlockFocus()

    rep = NSBitmapImageRep.imageRepWithData_(img.TIFFRepresentation())
    png_data = rep.representationUsingType_properties_(NSPNGFileType, None)
    png_data.writeToFile_atomically_(path, True)

iconset_dir = "/tmp/cmdc_AppIcon.iconset"
os.makedirs(iconset_dir, exist_ok=True)
sizes = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]
for sz, name in sizes:
    create_icon_png(sz, os.path.join(iconset_dir, name))
EOF
    iconutil -c icns /tmp/cmdc_AppIcon.iconset -o "$ICON_PATH"
    rm -rf /tmp/cmdc_AppIcon.iconset
fi

cp "$ICON_PATH" "$APP_DIR/Contents/Resources/AppIcon.icns"

# 4. Create Info.plist
cat << 'EOF' > "$APP_DIR/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>en</string>
    <key>CFBundleDisplayName</key>
    <string>cmdc</string>
    <key>CFBundleExecutable</key>
    <string>cmdc</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.gunkow.cmdc</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>cmdc</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleVersion</key>
    <string>0.1.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# 5. Compile native Mach-O launcher
echo "==> Compiling native launcher..."
clang -O2 \
  "-DCMDC_PROJECT_DIR=\"$ROOT\"" \
  "-DCMDC_VENV_DIR=\"$ROOT/.venv\"" \
  "-DCMDC_PYTHON_HOME=\"$PYTHON_HOME\"" \
  "-DCMDC_PYTHON_DYLIB=\"$PYTHON_DYLIB\"" \
  "-DCMDC_SITE_PACKAGES=\"$SITE_PACKAGES\"" \
  "-DCMDC_STDLIB=\"$STDLIB\"" \
  "$ROOT/scripts/launcher.c" -o "$APP_DIR/Contents/MacOS/cmdc"

# 6. Ad-hoc codesign
codesign --force --deep --sign - "$APP_DIR"

# 7. Install to /Applications
echo "==> Installing to $DEST..."
pkill -9 -f "cmdc" || true
sleep 1
rm -rf "$DEST"
cp -R "$APP_DIR" "$DEST"
touch "$DEST"

echo "==> Starting $DEST..."
open -a "$DEST"

echo "==> Done! cmdc.app is installed in Applications and running as a native Mach-O binary."
