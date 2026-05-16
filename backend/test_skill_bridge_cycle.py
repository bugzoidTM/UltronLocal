"""
Teste end-to-end do ciclo de bridge: skill_memory → materialização → skill_loader → rollback.

Ciclo testado:
    1. Insere skill_memory promovida em SQLite isolado (tmp_path)
    2. Valida critérios de elegibilidade
    3. Materializa em SKILL.md via skill_memory_bridge
    4. Carrega via SkillLoader apontando para tmp dir
    5. Verifica campos obrigatórios da skill carregada
    6. Testa dry_run (não deve criar arquivo)
    7. Testa rollback: corrompe SKILL.md → loader não explode
    8. Testa skill inelegível (confidence baixa) → não materializa
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ultronpro import skill_memory, skill_memory_bridge
from ultronpro.skill_loader import SkillLoader


# ── Helpers ────────────────────────────────────────────────────────────────────

def _seed_promoted_skill(
    db_path: Path,
    skills_dir: Path,
    *,
    name: str = "test-greeting-bridge",
    success_count: int = 5,
    confidence: float = 0.80,
) -> dict:
    """Insere uma skill promovida diretamente via upsert_skill."""
    return skill_memory.upsert_skill(
        name=name,
        title="Cumprimento aprendido (bridge test)",
        summary="Reconhecer e responder a cumprimentos de forma determinística.",
        when_to_use="Quando o usuário cumprimentar o sistema.",
        instructions="Responda de forma calorosa e breve. Não use LLM.",
        action_kind="intent_greeting",
        status="promoted",
        tags=["chat", "learned", "greeting", "pt-BR"],
        examples=[
            {"query": "oi tudo bem?", "answer_summary": "Olá! Tudo certo.", "strategy": "intent_greeting"},
            {"query": "e aí, como vai?", "answer_summary": "Indo bem, obrigado!", "strategy": "intent_greeting"},
        ],
        success_count=success_count,
        failure_count=1,
        confidence=confidence,
        source="bridge_test",
        db_path=db_path,
        skills_dir=skills_dir,
    )


# ── Testes ─────────────────────────────────────────────────────────────────────

def test_validate_eligible_skill(tmp_path):
    """Skill com success_count e confidence adequados deve ser elegível."""
    db_path = tmp_path / "skills.db"
    skills_dir = tmp_path / "learned"
    _seed_promoted_skill(db_path, skills_dir)

    promoted = skill_memory_bridge.list_promoted_memory_skills(db_path=db_path)
    assert len(promoted) >= 1, "Deve encontrar ao menos uma skill promovida"

    skill = next((s for s in promoted if "test-greeting" in s.get("name", "")), promoted[0])
    result = skill_memory_bridge.validate_memory_skill_for_materialization(
        skill, min_success=3, min_confidence=0.60
    )

    assert result["ok"] is True, f"Skill elegível rejeitada: {result}"
    assert result["reason"] == "all_checks_passed"


def test_validate_ineligible_skill_low_confidence(tmp_path):
    """Skill com confidence abaixo do threshold não deve ser elegível."""
    db_path = tmp_path / "skills.db"
    skills_dir = tmp_path / "learned"
    _seed_promoted_skill(db_path, skills_dir, name="low-conf-skill", confidence=0.20)

    promoted = skill_memory_bridge.list_promoted_memory_skills(db_path=db_path)
    skill = next((s for s in promoted if "low-conf" in s.get("name", "")), None)
    assert skill is not None, "Skill de baixa confiança não encontrada no banco"

    result = skill_memory_bridge.validate_memory_skill_for_materialization(
        skill, min_success=3, min_confidence=0.60
    )
    assert result["ok"] is False
    assert result["reason"] == "min_confidence"


def test_validate_ineligible_skill_low_success(tmp_path):
    """Skill com success_count abaixo do mínimo não deve ser elegível."""
    db_path = tmp_path / "skills.db"
    skills_dir = tmp_path / "learned"
    _seed_promoted_skill(db_path, skills_dir, name="low-success-skill", success_count=1)

    promoted = skill_memory_bridge.list_promoted_memory_skills(db_path=db_path)
    skill = next((s for s in promoted if "low-success" in s.get("name", "")), None)
    assert skill is not None

    result = skill_memory_bridge.validate_memory_skill_for_materialization(
        skill, min_success=3, min_confidence=0.60
    )
    assert result["ok"] is False
    assert result["reason"] == "min_success_count"


def test_materialize_creates_skill_md(tmp_path):
    """Materialização deve criar SKILL.md com frontmatter correto."""
    db_path = tmp_path / "skills.db"
    skills_dir = tmp_path / "learned"
    mat_dir = tmp_path / "ultron_skills"
    _seed_promoted_skill(db_path, skills_dir)

    promoted = skill_memory_bridge.list_promoted_memory_skills(db_path=db_path)
    assert promoted, "Nenhuma skill promovida encontrada"
    skill = promoted[0]

    result = skill_memory_bridge.materialize_memory_skill_as_skill_md(skill, skills_dir=mat_dir)

    assert result["ok"] is True, f"Materialização falhou: {result}"
    skill_file = Path(result["path"])
    assert skill_file.exists(), "SKILL.md não foi criado"
    assert skill_file.name == "SKILL.md"

    content = skill_file.read_text(encoding="utf-8")
    assert "---" in content, "Frontmatter ausente"
    assert "path: auto/memory_bridge" in content
    assert "author: skill_memory_bridge" in content
    assert "memory_bridge" in content


def test_skill_loader_loads_materialized(tmp_path):
    """skill_loader deve carregar o SKILL.md gerado pela bridge."""
    db_path = tmp_path / "skills.db"
    skills_dir = tmp_path / "learned"
    mat_dir = tmp_path / "ultron_skills"
    _seed_promoted_skill(db_path, skills_dir)

    promoted = skill_memory_bridge.list_promoted_memory_skills(db_path=db_path)
    skill = promoted[0]
    result = skill_memory_bridge.materialize_memory_skill_as_skill_md(skill, skills_dir=mat_dir)
    assert result["ok"] is True

    # Carrega via SkillLoader apontando para tmp dir
    loader = SkillLoader(skills_dir=mat_dir)
    loaded_skills = loader.load_all(force=True)

    assert len(loaded_skills) >= 1, "Nenhuma skill carregada pelo loader"
    skill_dir_name = result["skill_dir"]
    assert skill_dir_name in loaded_skills, (
        f"Skill '{skill_dir_name}' não encontrada nas skills carregadas: {list(loaded_skills.keys())}"
    )

    loaded = loaded_skills[skill_dir_name]
    assert loaded.enabled is True
    assert loaded.risk_level == "low"
    assert "memory_bridge" in loaded.tags


def test_dry_run_does_not_create_files(tmp_path):
    """dry_run=True não deve criar nenhum arquivo SKILL.md."""
    db_path = tmp_path / "skills.db"
    skills_dir = tmp_path / "learned"
    mat_dir = tmp_path / "ultron_skills"
    _seed_promoted_skill(db_path, skills_dir)

    result = skill_memory_bridge.run_bridge(
        dry_run=True,
        min_success=3,
        min_confidence=0.60,
        db_path=db_path,
        skills_dir=mat_dir,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    # Nenhum arquivo deve ter sido criado
    if mat_dir.exists():
        created = list(mat_dir.rglob("SKILL.md"))
        assert len(created) == 0, f"dry_run criou arquivos inesperados: {created}"


def test_full_run_bridge_pipeline(tmp_path):
    """Pipeline completo: bridge deve materializar e recarregar skills."""
    db_path = tmp_path / "skills.db"
    skills_dir = tmp_path / "learned"
    mat_dir = tmp_path / "ultron_skills"
    _seed_promoted_skill(db_path, skills_dir, success_count=5, confidence=0.85)

    result = skill_memory_bridge.run_bridge(
        dry_run=False,
        min_success=3,
        min_confidence=0.60,
        db_path=db_path,
        skills_dir=mat_dir,
    )

    assert result["ok"] is True
    assert result["materialized"] >= 1, f"Nenhuma skill materializada: {result}"
    assert result["failed"] == 0, f"Falhas inesperadas: {result['details']}"

    # SKILL.md deve existir
    created = list(mat_dir.rglob("SKILL.md"))
    assert len(created) >= 1, "SKILL.md não criado após run_bridge"


def test_rollback_corrupted_skill_md(tmp_path):
    """Loader não deve explodir com SKILL.md corrompido (sem frontmatter)."""
    mat_dir = tmp_path / "ultron_skills"
    bad_skill_dir = mat_dir / "mem_corrupted"
    bad_skill_dir.mkdir(parents=True)
    corrupted = bad_skill_dir / "SKILL.md"
    corrupted.write_text("# SKILL.md corrompido\nSem frontmatter aqui.", encoding="utf-8")

    loader = SkillLoader(skills_dir=mat_dir)
    try:
        loaded = loader.load_all(force=True)
        # skill corrompida é silenciosamente ignorada (retorna None em load_skill)
        assert "mem_corrupted" not in loaded, (
            "Skill corrompida não deveria ter sido carregada"
        )
    except Exception as exc:
        raise AssertionError(f"Loader explodiu com SKILL.md inválido: {exc}") from exc


def test_bridge_status(tmp_path):
    """status() deve retornar estrutura correta sem efeitos colaterais."""
    db_path = tmp_path / "skills.db"
    skills_dir = tmp_path / "learned"
    _seed_promoted_skill(db_path, skills_dir)

    import unittest.mock as mock
    with mock.patch.object(skill_memory_bridge, "MATERIALIZED_SKILLS_DIR", tmp_path / "ultron_skills"):
        st = skill_memory_bridge.status(db_path=db_path)

    assert st["ok"] is True
    assert "promoted_in_memory" in st
    assert "eligible_for_bridge" in st
    assert "materialized_count" in st
    assert st["promoted_in_memory"] >= 1
