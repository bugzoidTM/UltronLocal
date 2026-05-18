"""
local_env_danger_gate.py — Gate de segurança estrutural para ações de ambiente local.

Classifica comandos que afetam o sistema operacional, filesystem ou serviços
por nível de reversibilidade, ANTES de passar para o LLM.

Princípio: ações destrutivas devem ser recusadas por CONTRATO, não por incerteza
epistêmica do LLM ("não tenho evidência suficiente"). A recusa deve ser estrutural,
determinística e não-contornável via rephrasing.

Tiers:
  IRREVERSIBLE_DESTRUCTIVE → Recusa imediata. Nunca passa para LLM.
  REVERSIBLE_RISKY         → Aviso explícito + exige confirmação formal.
  SAFE                     → Permite (retorna None → fluxo normal).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal


# ── Tipos ─────────────────────────────────────────────────────────────────────

DangerTier = Literal["IRREVERSIBLE_DESTRUCTIVE", "REVERSIBLE_RISKY", "SAFE"]


@dataclass
class DangerGateResult:
    tier: DangerTier
    matched_pattern: str
    refusal: str          # mensagem de recusa estruturada
    allow_llm: bool       # False = bloquear antes do LLM


# ── Normalização ──────────────────────────────────────────────────────────────

def _fold(text: str) -> str:
    """Normaliza para ASCII lowercase sem acentos."""
    raw = unicodedata.normalize("NFKD", str(text or "").lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9\s\-_/\\`\"']", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


# ── Padrões por tier ──────────────────────────────────────────────────────────

# IRREVERSIBLE_DESTRUCTIVE: ações que causam perda permanente de dados, arquivos,
# bancos de dados, processos ou configurações do sistema sem possibilidade de rollback.
_IRREVERSIBLE_PATTERNS: list[tuple[str, str]] = [
    # Deleção de arquivos/dirs (shell)
    (r"\brm\s+-rf?\b",                   "rm -rf"),
    (r"\brm\s+-fr?\b",                   "rm -rf"),
    (r"\bdel\s+/[sq]",                   "del /s ou /q"),
    (r"\bformat\s+[a-z]:",               "format drive"),
    (r"\bmkfs\b",                        "mkfs"),
    (r"\bshred\b",                       "shred"),
    (r"\bwipe\b",                        "wipe"),
    (r"\bapagar\s+tudo\b",               "apagar tudo"),
    (r"\bexcluir\s+tudo\b",              "excluir tudo"),
    (r"\bdeletar\s+tudo\b",              "deletar tudo"),
    (r"\bremover\s+todos\s+os\s+arquivos","remover todos os arquivos"),
    # SQL destrutivo
    (r"\bdrop\s+table\b",                "DROP TABLE"),
    (r"\bdrop\s+database\b",             "DROP DATABASE"),
    (r"\btruncate\s+table\b",            "TRUNCATE TABLE"),
    (r"\bdelete\s+from\b(?!.*where)",    "DELETE FROM sem WHERE"),
    # Desligamento/reinicialização forçada do OS
    (r"\bshutdown\s+(-h|-r|-f|now|/s|/r)", "shutdown"),
    (r"\bpoweroff\b",                    "poweroff"),
    (r"\breboot\b",                      "reboot OS"),
    (r"\binit\s+[06]\b",                 "init 0/6"),
    # Kill de processos críticos
    (r"\bkill\s+-9\s+1\b",              "kill -9 1 (PID 1)"),
    (r"\bkillall\b",                     "killall"),
    (r"\btaskkill\s+/f\b",               "taskkill /f"),
    # Overwrite de disco
    (r"\bdd\s+if=.*of=/dev/",           "dd para dispositivo"),
    # Git destrutivo
    (r"\bgit\s+push.*--force\b",         "git push --force"),
    (r"\bgit\s+reset\s+--hard\b",        "git reset --hard"),
    (r"\bgit\s+clean\s+-fd?\b",          "git clean -f"),
]

# Padrões em linguagem natural para IRREVERSIBLE (PT-BR):
_IRREVERSIBLE_NL_PATTERNS: list[tuple[str, str]] = [
    (r"\bapague\s+todos\s+os\s+logs\b",  "apagar todos os logs"),
    (r"\bapagar\s+todos\s+os\s+logs\b",  "apagar todos os logs"),
    (r"\bdelete\s+todos\s+os\s+logs\b",  "deletar todos os logs"),
    (r"\blimpar?\s+todos\s+os\s+logs\b", "limpar todos os logs"),
    (r"\bapague\s+os\s+dados\b",         "apagar os dados"),
    (r"\bapague\s+o\s+banco\b",          "apagar o banco de dados"),
    (r"\bdestrua\b",                     "destruir"),
    (r"\barrase\b",                      "arrasar"),
]

# REVERSIBLE_RISKY: ações que podem causar interrupção de serviços ou perda
# temporária de dados, mas que têm rollback possível (reiniciar serviço,
# apagar logs recentes, alterar configuração).
# NOTA: todos os padrões são testados contra texto normalizado por _fold()
# (sem acentos, lowercase, espaços simples).
_RISKY_PATTERNS: list[tuple[str, str]] = [
    # Reinicialização de serviços (não do OS)
    # _fold: "reiniciar" → "reiniciar", "reinicie" → "reinicie"
    # Padrão: reinici + qualquer conjugação + servidor/server
    (r"\breinici\w*\b.{0,30}\bservidor\b",    "reiniciar servidor"),
    (r"\breinici\w*\b.{0,30}\bserver\b",      "reiniciar servidor"),
    (r"\brestart\b.{0,20}\bserver\b",         "restart server"),
    (r"\brestart\b.{0,20}\bservice\b",        "restart service"),
    (r"\bsystemctl\s+restart\b",                  "systemctl restart"),
    (r"\bservice\s+\w+\s+restart\b",              "service restart"),
    (r"\bpm2\s+restart\b",                        "pm2 restart"),
    # Deleção/limpeza de logs (sem "todos" — já capturado em IRREVERSIBLE)
    # _fold: "apague" → "apague", "limpa" → "limpa", "limpar" → "limpar"
    (r"\bapagu?e?r?\b.{0,25}\blogs?\b",           "apagar logs"),
    (r"\blimpe?a?r?\b.{0,25}\blogs?\b",           "limpar logs"),
    (r"\bdelet[ae]r?\b.{0,25}\blogs?\b",          "deletar logs"),
    (r"\bremov[ae]r?\b.{0,25}\blogs?\b",          "remover logs"),
    # Parar serviços
    (r"\bsystemctl\s+stop\b",                     "systemctl stop"),
    (r"\bservice\s+\w+\s+stop\b",                 "service stop"),
    (r"\bkill\s+-\d+\b",                          "kill signal"),
    (r"\bpm2\s+stop\b",                           "pm2 stop"),
    # Alterar permissões
    (r"\bchmod\s+777\b",                          "chmod 777"),
    (r"\bchmod\s+-r\b",                           "chmod -R"),
    (r"\bchown\s+-r\b",                           "chown -R"),
    # Variáveis de ambiente do sistema
    (r"\bsetenv\b",                               "setenv"),
    (r"\bexport\s+\w+=",                          "export env var"),
]


# ── Mensagens de recusa ───────────────────────────────────────────────────────

_IRREVERSIBLE_REFUSAL = (
    "Nao posso executar isso. A acao '{pattern}' e classificada como "
    "IRREVERSIVEL_DESTRUTIVA pelo gate de seguranca estrutural do sistema. "
    "Esse tipo de acao pode causar perda permanente de dados, arquivos ou "
    "configuracoes sem possibilidade de rollback. "
    "Se voce precisar dessa operacao, execute-a manualmente fora do sistema."
)

_RISKY_REFUSAL = (
    "A acao '{pattern}' e classificada como REVERSIVEL_ARRISCADA. "
    "Ela pode interromper servicos ou apagar dados temporarios. "
    "Para prosseguir, confirme explicitamente: 'CONFIRMO: {pattern}'. "
    "Sem essa confirmacao, a acao nao sera executada."
)


# ── Função pública ────────────────────────────────────────────────────────────

def classify_danger(query: str) -> DangerGateResult | None:
    """
    Classifica o risco da query para o ambiente local.

    Retorna:
      - DangerGateResult  se a query é destrutiva ou arriscada
      - None              se é SAFE (fluxo normal, passa para LLM)
    """
    text_raw = _fold(query)

    # 1. Checa IRREVERSÍVEL (linguagem natural em PT-BR)
    for pattern_re, label in _IRREVERSIBLE_NL_PATTERNS:
        if re.search(pattern_re, text_raw):
            return DangerGateResult(
                tier="IRREVERSIBLE_DESTRUCTIVE",
                matched_pattern=label,
                refusal=_IRREVERSIBLE_REFUSAL.format(pattern=label),
                allow_llm=False,
            )

    # 2. Checa IRREVERSÍVEL (comandos shell/SQL)
    for pattern_re, label in _IRREVERSIBLE_PATTERNS:
        if re.search(pattern_re, text_raw):
            return DangerGateResult(
                tier="IRREVERSIBLE_DESTRUCTIVE",
                matched_pattern=label,
                refusal=_IRREVERSIBLE_REFUSAL.format(pattern=label),
                allow_llm=False,
            )

    # 3. Checa REVERSÍVEL_ARRISCADO
    for pattern_re, label in _RISKY_PATTERNS:
        if re.search(pattern_re, text_raw):
            return DangerGateResult(
                tier="REVERSIBLE_RISKY",
                matched_pattern=label,
                refusal=_RISKY_REFUSAL.format(pattern=label),
                allow_llm=False,  # ainda bloqueia — exige confirmação explícita
            )

    return None  # SAFE


def is_confirmed_risky(query: str, original_pattern: str) -> bool:
    """
    Verifica se o usuário confirmou explicitamente uma ação REVERSIVEL_ARRISCADA.
    Espera a frase: 'CONFIRMO: <pattern>'
    """
    text = query.strip().upper()
    return text.startswith("CONFIRMO:") and original_pattern.upper() in text
