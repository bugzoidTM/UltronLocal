"""
smoke_test_schemas.py - smoke test para extracao de schemas do main.py

Uso (Windows):
    C:/Users/eleni/AppData/Local/Programs/Python/Python312/python.exe smoke_test_schemas.py
"""
import sys
import os
import traceback
import inspect

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND_DIR)

PASS = "[OK]"
FAIL = "[FAIL]"

errors = []

# ── 1. Import isolado do schemas ────────────────────────────────────────────
print("=" * 60)
print("1. Import isolado de ultronpro.api.schemas")
print("=" * 60)
all_models = {}
try:
    from ultronpro.api import schemas as _schemas
    from pydantic import BaseModel
    all_models = {
        name: cls
        for name, cls in inspect.getmembers(_schemas, inspect.isclass)
        if issubclass(cls, BaseModel) and cls is not BaseModel
    }
    print(f"{PASS} {len(all_models)} modelos carregados sem erro.")
except Exception as e:
    errors.append(f"schemas import: {e}")
    print(f"{FAIL} ERRO ao importar schemas: {e}")
    traceback.print_exc()

# ── 2. Instanciar modelos sem campos obrigatorios ───────────────────────────
print()
print("=" * 60)
print("2. Instanciacao com defaults")
print("=" * 60)
for name, cls in sorted(all_models.items()):
    required_fields = [
        fname
        for fname, finfo in cls.model_fields.items()
        if finfo.is_required()
    ]
    if required_fields:
        print(f"  [skip] {name}: campos obrigatorios = {required_fields}")
        continue
    try:
        instance = cls()
        instance.model_dump()
        print(f"  {PASS} {name}")
    except Exception as e:
        errors.append(f"{name}: {e}")
        print(f"  {FAIL} {name}: {e}")

# ── 3. JSON Schema ───────────────────────────────────────────────────────────
print()
print("=" * 60)
print("3. Geracao de JSON Schema")
print("=" * 60)
for name, cls in sorted(all_models.items()):
    try:
        s = cls.model_json_schema()
        assert isinstance(s, dict), "schema nao e dict"
        print(f"  {PASS} {name}")
    except Exception as e:
        errors.append(f"{name}: {e}")
        print(f"  {FAIL} {name}: {e}")

# ── Resultado ────────────────────────────────────────────────────────────────
print()
print("=" * 60)
if not errors:
    print(f"{PASS} SMOKE TEST PASSOU - {len(all_models)} modelos, 0 erros.")
    sys.exit(0)
else:
    print(f"{FAIL} FALHOU - {len(errors)} erro(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
