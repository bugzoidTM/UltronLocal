from ultronpro.ultron_ui.dynamic_tasks import DynamicTaskManager, validate_task_code


class DummyLlm:
    def complete(self, *args, **kwargs):
        raise AssertionError("IMC fallback should not call the LLM")


def test_imc_task_is_sandboxed_approved_and_executed(tmp_path):
    manager = DynamicTaskManager(root=tmp_path / "tasks", llm=DummyLlm())

    prepared = manager.prepare_task("Cria uma tarefa que calcula IMC")
    assert prepared["ok"] is True
    assert prepared["spec"]["filename"] == "calcular_imc.py"

    approved = manager.approve_task(prepared["spec"])
    assert approved["ok"] is True

    result = manager.execute_best_match("Calcula meu IMC: peso 70, altura 1.75")
    assert result["ok"] is True
    assert result["matched"] is True
    assert "22.9" in result["reply"]


def test_dynamic_task_validator_blocks_dangerous_imports():
    result = validate_task_code(
        "import os\n\n"
        "def run(command: str) -> str:\n"
        "    return os.listdir('.')\n"
    )

    assert result["ok"] is False
    assert result["error"].startswith("blocked_import")

