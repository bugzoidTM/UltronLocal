"""
UltronPRO Launcher
==================
Ponto de entrada único para distribuição. Este script:
  1. Descobre onde o Python está (mesmo que seja o Python embarcado no próprio .exe)
  2. Instala as dependências ausentes com pip
  3. Sobe o servidor uvicorn em background
  4. Aguarda o servidor responder e então abre a janela PyQt5
  5. Ao fechar a janela, encerra o servidor automaticamente

Pode ser compilado com PyInstaller para gerar um .exe portátil.
"""
from __future__ import annotations

import os
import sys
import subprocess
import threading
import time
import socket
import importlib
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

# ──────────────────────────────────────────────
# Caminhos
# ──────────────────────────────────────────────

def _resolve_base_dir() -> Path:
    """Retorna a raiz do projeto (pasta que contém 'backend/')."""
    # Quando compilado pelo PyInstaller, sys._MEIPASS aponta para o bundle
    if getattr(sys, "frozen", False):
        # O executável fica em build/dist/; subimos até a raiz
        return Path(sys.executable).resolve().parent.parent.parent
    # Rodando como script: __file__ está em build/launcher/
    return Path(__file__).resolve().parent.parent.parent

BASE_DIR = _resolve_base_dir()
BACKEND_DIR = BASE_DIR / "backend"
REQUIREMENTS_FILE = BACKEND_DIR / "requirements.txt"
MAIN_MODULE = "ultronpro.main:app"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

# ──────────────────────────────────────────────
# Janela de splash / progresso com tkinter
# (tkinter já vem na stdlib, zero dependência extra)
# ──────────────────────────────────────────────

class SplashWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("UltronPRO — Inicializando")
        self.root.configure(bg="#030a12")
        self.root.resizable(False, False)
        # Centraliza
        w, h = 520, 200
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.root.overrideredirect(True)   # sem barra de título

        tk.Label(
            self.root, text="ULTRON PRO", bg="#030a12", fg="#00d9ff",
            font=("Segoe UI", 22, "bold")
        ).pack(pady=(28, 4))

        self.label = tk.Label(
            self.root, text="Iniciando...", bg="#030a12", fg="#7af6ff",
            font=("Segoe UI", 11), wraplength=460
        )
        self.label.pack(pady=4)

        self.bar_frame = tk.Frame(self.root, bg="#061522", width=440, height=10)
        self.bar_frame.pack(pady=10)
        self.bar_frame.pack_propagate(False)
        self.bar = tk.Frame(self.bar_frame, bg="#00a6c8", width=0, height=10)
        self.bar.place(x=0, y=0, relheight=1.0)

        self._pct = 0
        self.root.update()

    def set_status(self, msg: str, pct: int | None = None) -> None:
        self.label.config(text=msg)
        if pct is not None:
            self._pct = pct
            target_w = int(440 * pct / 100)
            self.bar.place_configure(width=target_w)
        self.root.update()

    def close(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _python_exe() -> str:
    """Retorna o executável Python a usar."""
    return sys.executable


def _pip_install(packages: list[str], splash: SplashWindow) -> None:
    """Instala lista de pacotes com pip."""
    cmd = [_python_exe(), "-m", "pip", "install", "--quiet", "--no-warn-script-location"] + packages
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"pip falhou:\n{proc.stderr[-800:]}")


def _is_module_available(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def _server_ready() -> bool:
    """Tenta conectar ao servidor; retorna True se responder."""
    try:
        with socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=1):
            return True
    except OSError:
        return False


# ──────────────────────────────────────────────
# Etapa 1 — instalar dependências
# ──────────────────────────────────────────────

# Pacotes essenciais para a UI rodar (sem os pesados como sentence-transformers)
_CORE_DEPS = [
    "fastapi",
    "uvicorn",
    "httpx",
    "pydantic",
    "python-multipart",
    "python-dotenv",
    "openai",
    "groq",
    "anthropic",
    "sqlalchemy",
    "loguru",
    "tenacity",
    "jinja2",
    "PyYAML",
    "tiktoken",
    "networkx",
    "numpy",
    "PyQt5",
]

# Mapeamento módulo → pacote pip (quando o nome difere)
_MODULE_TO_PKG = {
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "multipart": "python-multipart",
    "sqlalchemy": "sqlalchemy",
    "PyQt5": "PyQt5",
}


def ensure_dependencies(splash: SplashWindow) -> None:
    splash.set_status("Verificando dependências...", 5)

    missing = []
    for dep in _CORE_DEPS:
        module = _MODULE_TO_PKG.get(dep, dep.replace("-", "_").split("[")[0])
        if not _is_module_available(module):
            missing.append(dep)

    if not missing:
        splash.set_status("Dependências OK.", 25)
        return

    splash.set_status(
        f"Instalando {len(missing)} pacote(s) necessários...\n"
        f"({', '.join(missing[:5])}{'...' if len(missing) > 5 else ''})\n"
        "Isso pode levar alguns minutos na primeira vez.",
        10,
    )

    # Instala em lotes para atualizar a barra
    chunk_size = max(1, len(missing) // 4)
    chunks = [missing[i: i + chunk_size] for i in range(0, len(missing), chunk_size)]
    for idx, chunk in enumerate(chunks):
        splash.set_status(f"Instalando: {', '.join(chunk)}", 10 + (idx + 1) * 12)
        _pip_install(chunk, splash)

    # Instalar também o requirements.txt completo em background (opcional pesados)
    if REQUIREMENTS_FILE.exists():
        splash.set_status("Instalando dependências completas (pode demorar)...", 24)
        try:
            subprocess.run(
                [_python_exe(), "-m", "pip", "install", "--quiet",
                 "--no-warn-script-location",
                 "--ignore-requires-python",
                 "-r", str(REQUIREMENTS_FILE)],
                capture_output=True,
                timeout=600,
            )
        except Exception:
            pass  # falha silenciosa; as principais já foram instaladas

    splash.set_status("Dependências instaladas.", 25)


# ──────────────────────────────────────────────
# Etapa 2 — subir servidor uvicorn
# ──────────────────────────────────────────────

_server_process: subprocess.Popen | None = None


def start_server(splash: SplashWindow) -> None:
    global _server_process

    if _server_ready():
        splash.set_status("Servidor já está rodando.", 55)
        return

    splash.set_status("Iniciando servidor UltronPRO...", 30)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)

    # Cria pasta de logs se não existir
    log_dir = BACKEND_DIR / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "launcher_server.log"

    _server_process = subprocess.Popen(
        [
            _python_exe(), "-m", "uvicorn",
            MAIN_MODULE,
            "--host", SERVER_HOST,
            "--port", str(SERVER_PORT),
            "--workers", "1",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=open(log_file, "w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    # Aguarda até 30 s
    splash.set_status("Aguardando servidor responder...", 35)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if _server_ready():
            splash.set_status("Servidor online!", 55)
            return
        if _server_process.poll() is not None:
            log_content = log_file.read_text(encoding="utf-8", errors="replace")[-1000:]
            raise RuntimeError(
                f"Servidor encerrou inesperadamente.\nLog:\n{log_content}"
            )
        time.sleep(0.4)
        splash.set_status(
            f"Aguardando servidor... ({int(deadline - time.monotonic())}s restantes)",
            35 + int((30 - (deadline - time.monotonic())) * 0.5),
        )

    raise RuntimeError(
        "Tempo limite aguardando o servidor. Verifique o log em:\n"
        f"{log_file}"
    )


# ──────────────────────────────────────────────
# Etapa 3 — abrir a UI PyQt5
# ──────────────────────────────────────────────

def launch_ui() -> int:
    # Adiciona o backend ao sys.path para os imports funcionarem
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from ultronpro.ultron_ui.app import main as ui_main
    return ui_main()


# ──────────────────────────────────────────────
# Encerramento limpo
# ──────────────────────────────────────────────

def shutdown_server() -> None:
    global _server_process
    if _server_process and _server_process.poll() is None:
        _server_process.terminate()
        try:
            _server_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _server_process.kill()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main() -> None:
    splash = SplashWindow()

    try:
        # 1. Dependências
        ensure_dependencies(splash)

        # 2. Servidor
        start_server(splash)

        # 3. UI
        splash.set_status("Abrindo interface...", 90)
        splash.close()

        exit_code = launch_ui()

    except Exception as exc:
        splash.close()
        # Janela de erro amigável
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "UltronPRO — Erro de inicialização",
            f"Ocorreu um erro ao iniciar o UltronPRO:\n\n{exc}\n\n"
            "Verifique se há conexão com a internet para baixar as dependências\n"
            "e se as portas 8000 não estão em uso.",
        )
        root.destroy()
        exit_code = 1

    finally:
        shutdown_server()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
