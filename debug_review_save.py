#!/usr/bin/env python3
"""
debug_review_save.py — Reproduce bug "save batch 2 review không hiện suggestions".

Sử dụng:
    cd /home/dmin/nano
    python debug_review_save.py [project_id]
"""
import sys
import json
import sqlite3
from pathlib import Path

PROJECT_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 1


def msg(s, status='INFO'):
    c = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m'}
    print(f"{c.get(status, '')}[{status}]\033[0m {s}")


conn = sqlite3.connect('data/dubeditor.db')
cur = conn.cursor()

# 1. List review groups + suggestions count per group
print(f"\n=== Review groups + suggestions của project {PROJECT_ID} ===")
cur.execute("""
SELECT g.group_index, g.range_start, g.range_end, g.status, g.saved_at,
       LENGTH(g.response) as resp_len,
       (SELECT COUNT(*) FROM simple_review_suggestions s
        WHERE s.project_id=? AND s.group_index=g.group_index) as total_sugg,
       (SELECT COUNT(*) FROM simple_review_suggestions s
        WHERE s.project_id=? AND s.group_index=g.group_index AND s.status='pending') as pending,
       (SELECT COUNT(*) FROM simple_review_suggestions s
        WHERE s.project_id=? AND s.group_index=g.group_index AND s.status='applied') as applied
FROM simple_review_groups g
WHERE g.project_id=?
ORDER BY g.group_index
""", (PROJECT_ID, PROJECT_ID, PROJECT_ID, PROJECT_ID))

rows = cur.fetchall()
if not rows:
    msg(f"Không có review group nào cho project {PROJECT_ID}", 'WARN')
    sys.exit()

print(f"{'idx':>3} {'range':>10} {'status':>8} {'resp_len':>8} {'sugg':>5} {'pend':>5} {'appl':>5}  saved_at")
for r in rows:
    idx, rs, re_, st, sv, rlen, tot, pen, app = r
    marker = "✓" if (pen > 0 or app > 0) else "✗"
    print(f" {marker} {idx:>2} {rs:>4}→{re_:<4} {st:>8} {rlen or 0:>8} {tot:>5} {pen:>5} {app:>5}  {sv or '(chưa save)'}")

# 2. Group nào response có nhưng suggestions = 0 → đó là bug
print()
msg("Phân tích:")
bug_groups = [r for r in rows if (r[5] or 0) > 100 and r[6] == 0]    # có response (>100 char) nhưng 0 suggestion
if bug_groups:
    msg(f"  {len(bug_groups)} group có response NHƯNG 0 suggestion → BUG", 'ERR')
    for r in bug_groups:
        msg(f"    Group {r[0]} (range {r[1]}→{r[2]}): response_len={r[5]}, suggestions=0", 'ERR')
    print()
    # Dump response của group đầu tiên có bug
    g_idx = bug_groups[0][0]
    cur.execute("SELECT response FROM simple_review_groups WHERE project_id=? AND group_index=?",
                (PROJECT_ID, g_idx))
    resp = cur.fetchone()[0]
    msg(f"Response của group {g_idx} (200 ký tự đầu):", 'INFO')
    print(f"  {resp[:300]}")
    print(f"  ...")
    print(f"  {resp[-200:]}")

    # Thử parse
    print()
    msg("Thử parse như BE làm:", 'INFO')
    sys.path.insert(0, '.')
    try:
        from dubeditor.simple.service_review import _parse_review_fixes
        fixes = _parse_review_fixes(resp)
        msg(f"  Parse thành công, {len(fixes)} fixes", 'OK')
        if fixes:
            msg(f"  Sample fix[0]: {fixes[0]}", 'INFO')
    except Exception as e:
        msg(f"  Parse fail: {e}", 'ERR')
        import traceback
        traceback.print_exc()
else:
    msg("  Tất cả group có response đều có suggestions", 'OK')

# 3. Status normalization - tổng pending
total_pending = sum((r[7] or 0) for r in rows)
total_applied = sum((r[8] or 0) for r in rows)
msg(f"Tổng: {total_pending} pending, {total_applied} applied", 'INFO')

conn.close()
