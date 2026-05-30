#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

NANO=/home/dmin/nano
[ -d "$NANO/dubeditor" ] || { echo "❌ Project nano không có ở $NANO"; exit 1; }

# BE: 3 file
declare -A BE_FILES=(
    ["service.py"]="$NANO/dubeditor/export/service.py"
    ["export_video.py"]="$NANO/dubeditor/routers/export_video.py"
    ["projects.py"]="$NANO/dubeditor/routers/projects.py"
)
for src in "${!BE_FILES[@]}"; do
    target="${BE_FILES[$src]}"
    [ -f "$src" ] || { echo "❌ $src không có"; exit 1; }
    cp "$target" "$target.bak_$(date +%s)" 2>/dev/null || true
    cp "$src" "$target"
    echo "✓ Copy $src → $target"
done

# FE: 1 file
FE_TARGET="$NANO/dubeditor_frontend/src/components/export/RenderQueuePanel.tsx"
cp "$FE_TARGET" "$FE_TARGET.bak_$(date +%s)" 2>/dev/null || true
cp RenderQueuePanel.tsx "$FE_TARGET"
echo "✓ Copy RenderQueuePanel.tsx"

# Xóa pycache
find "$NANO/dubeditor" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
echo "✓ Xóa __pycache__"

echo ""
echo "🎉 Restart server + rebuild FE:"
echo "   cd $NANO && python app.py"
echo "   cd $NANO/dubeditor_frontend && npm run build"
