#!/usr/bin/env python3
"""
patch_subtitlelist_no_oldconfig.py — Xóa references đến ConfigModal cũ trong SubtitleList.tsx.

Sau khi ConfigModal đã xóa, SubtitleList vẫn còn:
  - import { loadConfig, getApiKey, getRetranslateModel, getRetranslateThinking, getRetranslateContextWindow }
  - Sử dụng cfgOld fallback

Fix:
  - Bỏ import ConfigModal cũ
  - Dùng 100% simple config + retranslate_context_window từ config simple
"""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
F = ROOT / "dubeditor_frontend" / "src" / "components" / "SubtitleList.tsx"


def msg(s, status='INFO'):
    c = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m', 'SKIP': '\033[90m'}
    print(f"{c.get(status, '')}[{status}]\033[0m {s}")


def main():
    if not F.exists():
        msg(f"Không có {F}", 'ERR'); sys.exit(1)
    text = F.read_text(encoding='utf-8')

    if "from './ConfigModal'" not in text and "cfgOld" not in text:
        msg("Đã patch rồi — bỏ qua", 'SKIP')
        return

    backup = F.with_suffix(f'.tsx.bak_noconfig_{int(time.time())}')
    backup.write_text(text, encoding='utf-8')
    msg(f"Backup: {backup.name}", 'OK')

    new_text = text

    # 1) Xóa import từ ConfigModal
    new_text = re.sub(
        r"import\s+\{[^}]*\}\s+from\s+'\./ConfigModal'\s*\n",
        "",
        new_text,
    )

    # 2) Thay block handleRetranslate config-loading
    OLD_BLOCK = """    const cfgOld = loadConfig()
    const cfgSimple = loadSimpleConfig()
    // Ưu tiên simple config; fallback config cũ nếu trống
    const taskCfg = cfgSimple.tasks?.retranslate
    const provider = taskCfg?.provider || cfgOld.provider || 'gemini'
    const model = taskCfg?.model || getRetranslateModel(cfgOld)
    const thinking = taskCfg?.thinking ?? getRetranslateThinking(cfgOld)
    const apiKey = (cfgSimple.api_keys && cfgSimple.api_keys[provider as 'gemini'|'openai'|'deepseek'])
                  || getApiKey(cfgOld)"""
    NEW_BLOCK = """    const cfgSimple = loadSimpleConfig()
    const taskCfg = cfgSimple.tasks?.retranslate
    const provider = (taskCfg?.provider || 'gemini') as 'gemini' | 'openai' | 'deepseek'
    const model = taskCfg?.model || 'gemini-2.5-flash-lite'
    const thinking = taskCfg?.thinking ?? false
    const apiKey = cfgSimple.api_keys?.[provider] || ''"""

    if OLD_BLOCK in new_text:
        new_text = new_text.replace(OLD_BLOCK, NEW_BLOCK, 1)
        msg("Đã thay block config loading", 'OK')
    else:
        msg("Pattern OLD_BLOCK không match — debug context line ~497", 'WARN')

    # 3) Thay getRetranslateContextWindow(cfgOld) → constant
    new_text = re.sub(
        r"const\s+ctxN\s*=\s*getRetranslateContextWindow\s*\(\s*cfgOld\s*\)",
        "const ctxN = 2     // Bỏ pipeline cũ — default 2 dòng context trước/sau",
        new_text,
    )

    # Final: nếu vẫn còn ref đến cfgOld → cảnh báo
    if 'cfgOld' in new_text:
        msg(f"⚠ Vẫn còn 'cfgOld' trong file — cần kiểm tra thủ công", 'WARN')
        for i, line in enumerate(new_text.split('\n'), 1):
            if 'cfgOld' in line:
                print(f"   line {i}: {line.strip()}")

    F.write_text(new_text, encoding='utf-8')
    msg("Đã patch SubtitleList.tsx", 'OK')

    print()
    msg("Rebuild FE:", 'INFO')
    msg("  cd dubeditor_frontend && npm run build", 'INFO')


if __name__ == '__main__':
    main()
