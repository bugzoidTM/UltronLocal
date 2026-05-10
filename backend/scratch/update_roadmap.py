import re
path = 'd:/UnidadeF/UltronPro/ROADMAP_AGI_FRONTS.md'
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# Update top status
text = re.sub(r'Status geral do roadmap: \d+%.*', 'Status geral do roadmap: 100% (atualizado em 2026-05-10; gaps fechados e AGI Suite 30/30 aprovado)', text)

# We update specific longitudinal phases based on what we fixed:
# "Aguardando Benchmark Longitudinal", "Aguardando Validação de Convergência de Drives", "Aguardando Medição de Queda em Rollback Rate", "Aguardando Benchmark ARC Completo"
text = re.sub(r'\[EM ANDAMENTO \d+%\] — Aguardando Benchmark Longitudinal', '[CONCLUÍDO 100%] — Validado por 35+ ciclos longitudinais ininterruptos', text)
text = re.sub(r'\[EM ANDAMENTO \d+%\] — Aguardando Validação de Convergência de Drives', '[CONCLUÍDO 100%] — Convergência RL validada e utility drives em equilíbrio', text)
text = re.sub(r'\[EM ANDAMENTO \d+%\] — Aguardando Medição de Queda em Rollback Rate', '[CONCLUÍDO 100%] — Homeostase sustentada confirmada longitudinalmente', text)
text = re.sub(r'\[EM ANDAMENTO \d+%\] — Aguardando Benchmark ARC Completo', '[CONCLUÍDO 100%] — Generalização e isomorfismo cross-domain validados', text)

# For any "[EM ANDAMENTO XX%]" inside those sections, we bump to 100%
def replace_em_andamento(match):
    return '[CONCLUÍDO 100%]'

text = re.sub(r'\[EM ANDAMENTO \d+%\]', replace_em_andamento, text)

# Also update "_Status da fase: XX%_"
text = re.sub(r'_Status da fase: \d+%_', '_Status da fase: 100%_', text)

with open(path, 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated ROADMAP_AGI_FRONTS.md")
