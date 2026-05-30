#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
TARGET=/home/dmin/nano/dubeditor_frontend/src/components/VideoPlayer.tsx
[ -f VideoPlayer.tsx ] || { echo "❌ VideoPlayer.tsx không có"; exit 1; }
[ -d "$(dirname $TARGET)" ] || { echo "❌ folder không có"; exit 1; }
cp "$TARGET" "$TARGET.bak_$(date +%s)" 2>/dev/null || true
cp VideoPlayer.tsx "$TARGET"
echo "✓ Copy VideoPlayer.tsx"
grep -q "class StemEngine" "$TARGET" && echo "✓ Verify OK" || echo "❌ Verify FAIL"
echo ""
echo "🎉 Build lại FE:"
echo "   cd /home/dmin/nano/dubeditor_frontend && npm run build"
