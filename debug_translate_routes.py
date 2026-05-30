#!/usr/bin/env python3
"""
debug_translate_routes.py — Check translate router có được include không.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))


def msg(s, status='INFO'):
    c = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m'}
    print(f"{c.get(status, '')}[{status}]\033[0m {s}")


print("\n=== Step 1: Import translate module ===")
try:
    from dubeditor.routers import translate
    msg(f"  ✓ {translate.__file__}")
    if hasattr(translate, 'router'):
        ev_router = translate.router
        msg(f"  Routes in translate.router:")
        retranslate_routes = []
        for route in ev_router.routes:
            methods = getattr(route, 'methods', set())
            path = getattr(route, 'path', '?')
            name = getattr(route, 'name', '?')
            if 'retranslate' in path:
                retranslate_routes.append((','.join(sorted(methods)), path, name))
        msg(f"  Tổng cộng {len(ev_router.routes)} routes, {len(retranslate_routes)} chứa 'retranslate':")
        for m, p, n in retranslate_routes:
            print(f"    {m:8s} {p:60s} → {n}")
except Exception as e:
    msg(f"  ✗ Import FAILED: {e}", 'ERR')
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== Step 2: Import main router ===")
try:
    from dubeditor import router as main_router_mod
    msg(f"  ✓ {main_router_mod.__file__}")
    main_router = main_router_mod.router

    msg(f"  Routes có 'translate':")
    translate_routes = []
    for route in main_router.routes:
        methods = getattr(route, 'methods', set())
        path = getattr(route, 'path', '?')
        if 'translate' in path:
            translate_routes.append((','.join(sorted(methods)), path))
    for m, p in translate_routes[:25]:
        marker = '🎯' if 'retranslate' in p else '  '
        print(f"   {marker} {m:8s} {p}")
    if len(translate_routes) > 25:
        print(f"   ... và {len(translate_routes)-25} routes khác")
except Exception as e:
    msg(f"  ✗ Import main router FAILED: {e}", 'ERR')
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== Step 3: Test full app routes ===")
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location("nano_app", ROOT / "app.py")
    nano_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nano_app)
    app = nano_app.app

    found = []
    for route in app.routes:
        methods = getattr(route, 'methods', set())
        path = getattr(route, 'path', '?')
        if 'retranslate' in path:
            found.append((','.join(sorted(methods)), path))

    if not found:
        msg("  ✗ KHÔNG TÌM THẤY route nào chứa 'retranslate' trong app!", 'ERR')
        msg("  → translate router không được include hoặc lỗi import", 'WARN')
    else:
        msg(f"  ✓ Tìm thấy {len(found)} routes có 'retranslate':")
        for m, p in found:
            print(f"     {m:8s} {p}")
except Exception as e:
    msg(f"  ✗ Load app.py FAILED: {e}", 'ERR')
    import traceback
    traceback.print_exc()

print()
msg("Xong.")
