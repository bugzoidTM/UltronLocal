from pathlib import Path

import yaml


def test_swarm_stack_includes_internal_qwen_inference_service():
    stack = yaml.safe_load(Path("deploy/docker-stack.swarm.yml").read_text(encoding="utf-8"))
    services = stack["services"]

    main_env = services["ultronpro"]["environment"]
    assert "ULTRON_OPENAI_COMPAT_QWEN_URL=http://ultronpro_infer:8025" in main_env

    infer = services["ultronpro_infer"]
    assert infer["image"] == "ultronpro_trainer:local"
    assert infer["command"] == [
        "uvicorn",
        "ultronpro.inference_api:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8025",
    ]
    assert any(str(port).endswith("18025:8025") for port in infer["ports"])
    assert "Nutef" in infer["networks"]


def test_trainer_dockerfile_builds_inference_api_image():
    dockerfile = Path("backend/Dockerfile.trainer")

    assert dockerfile.exists()
    text = dockerfile.read_text(encoding="utf-8")
    assert "requirements-trainer.txt" in text
    assert "ultronpro.inference_api:app" in text
