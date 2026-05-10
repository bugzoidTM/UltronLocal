import sys

path = "ultronpro/main.py"
content = open(path, "r", encoding="utf-8").read()

if "/api/rl/convergence" in content:
    print("Endpoint already exists")
    sys.exit(0)

# We anchor right after the selftest function body (works regardless of \r\n vs \n)
anchor = "return online_rl_loop.run_selftest()"
idx = content.find(anchor)
if idx == -1:
    print("ANCHOR NOT FOUND")
    sys.exit(1)

pos = idx + len(anchor)

# New block to insert (using \n — Python will handle it)
new_block = "\n\n\n@app.get('/api/rl/convergence')\nasync def rl_convergence_status(recompute: bool = False):\n    \"\"\"Gap 3 \u2013 Longitudinal RL convergence proof.\n\n    Returns per-arm EMA reward series, global reward trend (first vs last half),\n    EMA decay / lock-in check, and roadmap criteria pass/fail scoring.\n    Query param: recompute=true forces fresh computation (bypasses 5-min cache).\n    \"\"\"\n    from ultronpro import rl_convergence_report\n    if recompute:\n        return await asyncio.to_thread(rl_convergence_report.compute)\n    return await asyncio.to_thread(rl_convergence_report.status)\n"

new_content = content[:pos] + new_block + content[pos:]
open(path, "w", encoding="utf-8").write(new_content)
print("Endpoint inserted OK")
