#!/usr/bin/env bash
set -e

if [ -z "$1" ]; then
  echo "Usage: bash apply.sh <NANO_ROOT>"
  exit 1
fi

NANO_ROOT="$(cd "$1" && pwd)"
PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$NANO_ROOT/srt_translator_v2" ]; then
  echo "❌ $NANO_ROOT không phải NANO root"
  exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  APPLY v4.5 PATCH (v1/v2 redefinition + SPEAKER_WRONG)"
echo "  NANO root: $NANO_ROOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "→ Copy files..."
cp -v "$PATCH_DIR/srt_translator_v2/prompts/v4_manual/translate_mega.txt"      "$NANO_ROOT/srt_translator_v2/prompts/v4_manual/"
cp -v "$PATCH_DIR/srt_translator_v2/prompts/v4_manual/review_pass2_polish.txt" "$NANO_ROOT/srt_translator_v2/prompts/v4_manual/"
cp -v "$PATCH_DIR/srt_translator_v2/manual/parsers_mega.py"                    "$NANO_ROOT/srt_translator_v2/manual/"

echo ""
echo "→ Clear cache..."
find "$NANO_ROOT/srt_translator_v2" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "✓ DONE — Restart backend để áp dụng"
echo ""
echo "Test: Build lại prompt Stage 2 (Translate) — xem section v1/v2 mới"
