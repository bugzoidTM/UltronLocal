import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def test_uvicorn_file_logger_compacts_in_place(tmp_path):
    from ultronpro.uvicorn_file_logger import CompactingSingleFileHandler

    log_path = tmp_path / "uvicorn_live.log"
    logger = logging.getLogger("test_uvicorn_file_logger_compacts_in_place")
    logger.handlers = []
    logger.propagate = False
    logger.setLevel(logging.INFO)

    handler = CompactingSingleFileHandler(log_path, max_bytes=1024, keep_bytes=256)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    try:
        for idx in range(80):
            logger.info("line-%02d %s", idx, "x" * 40)
    finally:
        handler.close()
        logger.handlers = []

    text = log_path.read_text(encoding="utf-8")
    assert "compacted_at=" in text
    assert "line-79" in text
    assert len(text.encode("utf-8")) < 1536
