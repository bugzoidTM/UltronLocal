from __future__ import annotations

import os
import math
import random
import re
import sys
import threading
import time
from typing import Any

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, QPointF, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .activation import ActivationGate, wake_phrase_variants
from .config import load_config, preset_for, provider_label, save_config, validate_cloud_config
from .dynamic_tasks import DynamicTaskManager
from .local_llm import UltronLLMClient
from .stt import VoskMicrophoneLoop, dependency_status
from .tts import PiperSpeaker


_VOICE_FILLERS = {
    "a",
    "e",
    "é",
    "o",
    "os",
    "as",
    "um",
    "uma",
    "hum",
    "hã",
    "oi",
    "olá",
    "ola",
    "não",
    "nao",
    "ah",
    "uh",
}
_VOICE_COMMAND_HINTS = {
    "calcula",
    "calcular",
    "cria",
    "crie",
    "tarefa",
    "imc",
    "status",
    "hora",
    "horas",
    "abre",
    "abrir",
    "pesquisa",
    "procura",
    "resuma",
    "explique",
    "explica",
    "responda",
    "quem",
    "qual",
    "quando",
    "onde",
    "como",
    "porque",
    "por",
    "ultron",
    "acende",
    "acender",
    "apaga",
    "apagar",
    "liga",
    "ligar",
    "desliga",
    "desligar",
    "dispositivo",
    "dispositivos",
    "luz",
    "luzes",
    "lampada",
    "lâmpada",
    "varrer",
    "rede",
    "confirmo",
    "cancelar",
}

_RUNTIME_QUERY_HINTS = {
    "usa",
    "usando",
    "está",
    "esta",
    "tá",
    "ta",
    "qual",
    "como",
    "rodando",
    "atual",
}


def _norm_command(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


class PulseWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._phase = 0.0
        self._target_level = 0.0
        self._level = 0.0
        self._mode = "locked"
        rng = random.Random(1979)
        self._particles = [
            {
                "angle": rng.random() * math.tau,
                "radius": rng.uniform(0.10, 0.48),
                "speed": rng.uniform(-0.9, 1.25),
                "size": rng.uniform(1.0, 3.2),
                "twinkle": rng.random() * math.tau,
            }
            for _ in range(int(os.getenv("ULTRON_UI_PARTICLES", "96") or 96))
        ]
        self.setMinimumSize(220, 220)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(os.getenv("ULTRON_UI_HUD_FRAME_MS", "50") or 50))

    def set_audio_level(self, level: float) -> None:
        self._target_level = max(0.0, min(1.0, float(level or 0.0)))

    def set_mode(self, mode: str) -> None:
        self._mode = str(mode or "locked")

    def _tick(self) -> None:
        self._phase = (self._phase + 0.035) % 1.0
        self._level = self._level * 0.78 + self._target_level * 0.22
        self._target_level *= 0.86
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        center = QPointF(rect.width() / 2, rect.height() / 2)
        size = min(rect.width(), rect.height())
        radius = size * (0.29 + self._level * 0.06)
        pulse = size * (0.34 + self._phase * 0.20 + self._level * 0.10)

        bg = QColor(2, 7, 14) if self._mode != "speaking" else QColor(5, 8, 18)
        painter.fillRect(rect, bg)
        color = {
            "locked": QColor(0, 145, 205),
            "listening": QColor(0, 235, 255),
            "processing": QColor(255, 210, 98),
            "speaking": QColor(90, 255, 178),
        }.get(self._mode, QColor(0, 235, 255))

        for particle in self._particles:
            angle = particle["angle"] + self._phase * particle["speed"] * math.tau * 0.08
            orbit = size * particle["radius"] * (1.0 + self._level * 0.55)
            wobble = math.sin(self._phase * math.tau + particle["twinkle"]) * size * 0.012 * (1 + self._level)
            x = center.x() + math.cos(angle) * (orbit + wobble)
            y = center.y() + math.sin(angle) * (orbit + wobble)
            if not rect.adjusted(-8, -8, 8, 8).contains(int(x), int(y)):
                continue
            alpha = int(50 + 145 * self._level + 45 * (0.5 + 0.5 * math.sin(self._phase * math.tau + particle["twinkle"])))
            star = QColor(color)
            star.setAlpha(max(35, min(235, alpha)))
            painter.setPen(QPen(star, particle["size"] * (1.0 + self._level * 1.4)))
            painter.drawPoint(QPointF(x, y))

        for idx, alpha in enumerate((45, 30, 18)):
            ring = QColor(color)
            ring.setAlpha(alpha + int(self._level * 45))
            pen = QPen(ring, 2)
            painter.setPen(pen)
            painter.drawEllipse(center, pulse + idx * 15, pulse + idx * 15)
        painter.setPen(QPen(color, 3 + self._level * 3))
        painter.drawEllipse(center, radius, radius)
        core = QColor(180, 250, 255)
        if self._mode == "speaking":
            core = QColor(196, 255, 218)
        painter.setPen(QPen(core, 1))
        painter.drawEllipse(center, radius * 0.62, radius * 0.62)
        painter.setPen(QPen(color, 6 + self._level * 6))
        painter.drawArc(
            int(center.x() - radius),
            int(center.y() - radius),
            int(radius * 2),
            int(radius * 2),
            int(360 * self._phase * 16),
            int(100 * 16),
        )


class RecognizerThread(QThread):
    text_ready = pyqtSignal(str)
    partial_ready = pyqtSignal(str)
    level_ready = pyqtSignal(float)
    status_ready = pyqtSignal(str)
    error_ready = pyqtSignal(str)

    def __init__(self, *, wake_mode: bool) -> None:
        super().__init__()
        self._stop = threading.Event()
        self.wake_mode = bool(wake_mode)

    def run(self) -> None:
        try:
            grammar = wake_phrase_variants() + ["[unk]"] if self.wake_mode else None
            loop = VoskMicrophoneLoop(grammar=grammar)
            loop.run(
                on_text=self.text_ready.emit,
                on_partial=self.partial_ready.emit,
                on_level=self.level_ready.emit,
                on_status=self.status_ready.emit,
                stop_event=self._stop,
            )
        except Exception as exc:
            self.error_ready.emit(f"STT offline indisponível: {type(exc).__name__}: {str(exc)[:180]}")

    def stop(self) -> None:
        self._stop.set()


class CommandWorker(QThread):
    done = pyqtSignal(dict)

    def __init__(self, command: str, task_manager: DynamicTaskManager, llm: UltronLLMClient) -> None:
        super().__init__()
        self.command = command
        self.task_manager = task_manager
        self.llm = llm

    def run(self) -> None:
        try:
            if self.task_manager.wants_task_creation(self.command):
                prepared = self.task_manager.prepare_task(self.command)
                prepared["kind"] = "task_prepare"
                self.done.emit(prepared)
                return

            task_result = self.task_manager.execute_best_match(self.command)
            if task_result.get("matched") and task_result.get("ok"):
                self.done.emit({"kind": "reply", "reply": task_result.get("reply") or "Tarefa executada.", "task": task_result})
                return
            if task_result.get("matched") and not task_result.get("ok"):
                self.done.emit({"kind": "reply", "reply": "A tarefa falhou e foi revertida ou desativada.", "task": task_result})
                return

            fast = self._fast_reply(self.command)
            if fast:
                self.done.emit({"kind": "reply", "reply": fast, "fast": True})
                return

            try:
                reply = self.llm.voice_reply(self.command)
                route = self.llm.last_route
            except Exception as exc:
                reply = f"Modelo local e fallback indisponíveis: {str(exc)[:160]}. Configure o fallback em nuvem no botão Config."
                route = "unavailable"
            self.done.emit({"kind": "reply", "reply": reply or "Não consegui responder agora.", "route": route})
        except Exception as exc:
            self.done.emit({"kind": "error", "error": f"{type(exc).__name__}: {str(exc)[:220]}"})

    def _fast_reply(self, command: str) -> str:
        text = _norm_command(command)
        now = time.localtime()
        if _looks_like_runtime_query(text):
            return self.llm.runtime_description()
        if text in {"oi ultron", "ola ultron", "olá ultron", "ultron"}:
            return "Estou ouvindo."
        if "que horas" in text or text in {"hora", "horas"}:
            return time.strftime("Agora são %H:%M.", now)
        if "tarefas" in text and ("lista" in text or "status" in text):
            count = len(self.task_manager.list_approved())
            return f"Tenho {count} tarefa dinâmica aprovada."
        if text in {"status", "status do sistema"}:
            return "Ultron UI ativo, voz local ligada."
        return ""


def _looks_like_runtime_query(text: str) -> bool:
    if "rota" in text or "llm" in text:
        return True
    return "modelo" in text and any(hint in text for hint in _RUNTIME_QUERY_HINTS)


class ApprovalDialog(QDialog):
    def __init__(self, spec: dict[str, Any], sandbox: dict[str, Any] | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Aprovar tarefa dinâmica")
        self.resize(820, 620)
        layout = QVBoxLayout(self)
        title = QLabel(str(spec.get("name") or "Nova tarefa"))
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        desc = QLabel(str(spec.get("description") or "Sem descrição."))
        desc.setWordWrap(True)
        layout.addWidget(desc)
        if sandbox:
            layout.addWidget(QLabel(f"Sandbox: {'OK' if sandbox.get('ok') else 'falhou'} | saída: {str(sandbox.get('stdout') or sandbox.get('error') or '')[:220]}"))
        self.code = QPlainTextEdit(str(spec.get("code") or ""))
        self.code.setReadOnly(True)
        layout.addWidget(self.code, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Aprovar")
        buttons.button(QDialogButtonBox.Cancel).setText("Rejeitar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ConfigDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Config Ultron UI")
        self.resize(620, 430)
        self.config = load_config()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        local = self.config.get("local") or {}
        cloud = self.config.get("cloud") or {}

        self.local_enabled = QCheckBox("Usar Qwen local primeiro")
        self.local_enabled.setChecked(bool(local.get("enabled", True)))
        self.local_url = QLineEdit(str(local.get("base_url") or "http://127.0.0.1:8025"))
        self.local_timeout = QSpinBox()
        self.local_timeout.setRange(3, 120)
        self.local_timeout.setValue(int(local.get("timeout_sec") or 9))

        self.cloud_enabled = QCheckBox("Usar nuvem grátis como fallback quando local falhar")
        self.cloud_enabled.setChecked(bool(cloud.get("enabled")))
        self.provider = QComboBox()
        for provider in ("free_auto", "pollinations", "g4f"):
            self.provider.addItem(provider_label(provider), provider)
        idx = self.provider.findData(str(cloud.get("provider") or "free_auto"))
        self.provider.setCurrentIndex(max(0, idx))
        self.provider.currentIndexChanged.connect(lambda _idx: self._provider_changed(force=True))

        self.base_url = QLineEdit(str(cloud.get("base_url") or ""))
        self.model = QLineEdit(str(cloud.get("model") or ""))
        self.api_key = QLineEdit(str(cloud.get("api_key") or ""))
        self.api_key.setEchoMode(QLineEdit.Password)
        self.cloud_timeout = QSpinBox()
        self.cloud_timeout.setRange(5, 180)
        self.cloud_timeout.setValue(int(cloud.get("timeout_sec") or 18))
        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(32, 2048)
        self.max_tokens.setValue(int(cloud.get("max_tokens") or 160))
        self._provider_changed(force=False)

        test_button = QPushButton("Testar fallback")
        test_button.clicked.connect(self._test_fallback)

        form.addRow("Local", self.local_enabled)
        form.addRow("URL local", self.local_url)
        form.addRow("Timeout local (s)", self.local_timeout)
        form.addRow("Nuvem", self.cloud_enabled)
        form.addRow("Rotação grátis", self.provider)
        form.addRow("", test_button)
        form.addRow("Timeout nuvem (s)", self.cloud_timeout)
        form.addRow("Max tokens", self.max_tokens)
        layout.addLayout(form)

        note = QLabel("Sem API key: a UI rotaciona provedores gratuitos/keyless. OpenRouter com chave não é necessário para este modo.")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Salvar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _provider_changed(self, force: bool = False) -> None:
        provider = str(self.provider.currentData() or "custom")
        preset = preset_for(provider)
        if force or not self.base_url.text().strip():
            self.base_url.setText(str(preset.get("base_url") or ""))
        if force or not self.model.text().strip():
            self.model.setText(str(preset.get("model") or ""))

    def output_config(self) -> dict[str, Any]:
        return {
            "local": {
                "enabled": self.local_enabled.isChecked(),
                "base_url": self.local_url.text().strip(),
                "timeout_sec": int(self.local_timeout.value()),
            },
            "cloud": {
                "enabled": self.cloud_enabled.isChecked(),
                "provider": str(self.provider.currentData() or "custom"),
                "base_url": self.base_url.text().strip(),
                "model": self.model.text().strip(),
                "api_key": "",
                "timeout_sec": int(self.cloud_timeout.value()),
                "max_tokens": int(self.max_tokens.value()),
            },
        }

    def accept(self) -> None:
        cfg = self.output_config()
        ok, err = validate_cloud_config(cfg)
        if not ok:
            QMessageBox.warning(self, "Config incompleta", err)
            return
        super().accept()

    def _test_fallback(self) -> None:
        cfg = self.output_config()
        ok, err = validate_cloud_config(cfg)
        if not ok:
            QMessageBox.warning(self, "Config incompleta", err)
            return
        try:
            from .local_llm import CloudFallbackClient

            reply = CloudFallbackClient(cfg["cloud"]).complete(
                "Responda apenas OK.",
                system="Teste rápido de conectividade.",
                max_tokens=16,
                temperature=0.0,
            )
            QMessageBox.information(self, "Fallback OK", f"Resposta: {reply[:160] or 'OK'}")
        except Exception as exc:
            QMessageBox.warning(self, "Fallback falhou", f"{type(exc).__name__}: {str(exc)[:260]}")


class UltronWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Ultron UI")
        self.resize(1180, 760)
        self.gate = ActivationGate(max_denied_attempts=3)
        self.llm = UltronLLMClient()
        self.tasks = DynamicTaskManager(llm=self.llm)
        self.speaker = PiperSpeaker(status_callback=self._append_system)
        self.recognizer: RecognizerThread | None = None
        self.worker: CommandWorker | None = None
        self._speaking_until = 0.0
        self._ignore_voice_until = 0.0
        self._last_command_norm = ""
        self._last_command_ts = 0.0
        self._last_suppressed_ts = 0.0
        self._speak_visual_timer = QTimer(self)
        self._speak_visual_timer.timeout.connect(self._tick_speaking_visual)
        self._speak_visual_timer.start(45)
        self._build_ui()
        self._apply_style()
        self._refresh_task_list()
        QTimer.singleShot(500, self._startup_sequence)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.pulse = PulseWidget()
        left_layout.addWidget(self.pulse)
        self.status = QLabel("Inicializando")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setObjectName("status")
        left_layout.addWidget(self.status)
        button_row = QHBoxLayout()
        self.mic_button = QPushButton("Ativar microfone")
        self.mic_button.clicked.connect(self._toggle_microphone)
        self.config_button = QPushButton("Config")
        self.config_button.clicked.connect(self._open_config)
        button_row.addWidget(self.mic_button, 1)
        button_row.addWidget(self.config_button)
        left_layout.addLayout(button_row)
        self.task_list = QListWidget()
        left_layout.addWidget(QLabel("Tarefas aprovadas"))
        left_layout.addWidget(self.task_list, 1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        right_layout.addWidget(self.log, 1)
        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Digite um comando ou a palavra de ativação")
        self.input.returnPressed.connect(self._submit_typed)
        self.send_button = QPushButton("Enviar")
        self.send_button.clicked.connect(self._submit_typed)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_button)
        right_layout.addLayout(input_row)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([360, 820])
        self.setCentralWidget(central)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #030a12; color: #d7fbff; font-family: Segoe UI; }
            QLabel#status { color: #7af6ff; font-size: 18px; padding: 12px; border: 1px solid #0d6a80; }
            QLabel#dialogTitle { color: #00d9ff; font-size: 20px; font-weight: 600; }
            QPlainTextEdit, QLineEdit, QListWidget {
                background: #061522; border: 1px solid #0b5f7a; color: #e7fdff;
                selection-background-color: #0d7894; padding: 8px;
            }
            QPushButton {
                background: #08283a; border: 1px solid #00a6c8; color: #dffcff;
                padding: 10px 14px; font-weight: 600;
            }
            QPushButton:hover { background: #0a3d58; border-color: #3eeaff; }
            QSplitter::handle { background: #08202f; }
            """
        )

    def _startup_sequence(self) -> None:
        self._append_system("Inicializando sistemas... Ativação por voz exigida!")
        self.status.setText("Ativação por voz exigida")
        self._say("Inicializando sistemas... Ativação por voz exigida!")
        self._start_microphone_if_possible()

    def _start_microphone_if_possible(self) -> None:
        deps = dependency_status()
        missing = [name for name, state in deps.items() if state != "ok"]
        if missing:
            self._append_system("STT offline incompleto: " + ", ".join(f"{m}={deps[m]}" for m in missing))
            self.status.setText("Modo texto ativo")
            return
        self._start_microphone()

    def _toggle_microphone(self) -> None:
        if self.recognizer and self.recognizer.isRunning():
            self.recognizer.stop()
            self.recognizer.wait(800)
            self.recognizer = None
            self.mic_button.setText("Ativar microfone")
            self.status.setText("Microfone pausado")
            return
        self._start_microphone()

    def _start_microphone(self) -> None:
        if self.recognizer and self.recognizer.isRunning():
            return
        self.recognizer = RecognizerThread(wake_mode=not self.gate.activated)
        self.recognizer.text_ready.connect(self._handle_transcript)
        self.recognizer.partial_ready.connect(self._handle_partial)
        self.recognizer.level_ready.connect(self._handle_audio_level)
        self.recognizer.status_ready.connect(self._append_system)
        self.recognizer.error_ready.connect(self._append_system)
        self.recognizer.start()
        self.mic_button.setText("Pausar microfone")
        self.pulse.set_mode("listening")

    def _restart_microphone_for_commands(self) -> None:
        if self.recognizer and self.recognizer.isRunning():
            self.recognizer.stop()
            self.recognizer.wait(900)
            self.recognizer = None
        QTimer.singleShot(250, self._start_microphone)

    def _submit_typed(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._handle_transcript(text, from_voice=False)

    def _handle_transcript(self, text: str, from_voice: bool = True) -> None:
        clean = str(text or "").strip()
        if not clean:
            return
        if not self.gate.activated and from_voice:
            self._append_user(clean)
            result = self.gate.handle_transcript(clean)
            self.status.setText(result.message)
            self._append_system(result.message)
            self._say(result.message)
            if result.state == "activated":
                self._restart_microphone_for_commands()
            if result.state == "lockout":
                QTimer.singleShot(1800, self.close)
            return
        if not self.gate.activated and not from_voice:
            self.gate.activated = True
            self.status.setText("Modo texto ativo")
            self._append_system("Entrada por texto ativada; comandos livres liberados.")
        if from_voice and not self._accept_voice_command(clean):
            return
        self._append_user(clean)
        self._run_command(clean)

    def _run_command(self, command: str) -> None:
        if self.worker and self.worker.isRunning():
            self.status.setText("Ocupado; aguardando resposta")
            return
        self.status.setText("Processando localmente")
        self.pulse.set_mode("processing")
        self._pause_microphone()
        self._ignore_voice_until = time.monotonic() + 1.5
        self.worker = CommandWorker(command, self.tasks, self.llm)
        self.worker.done.connect(self._handle_worker_done)
        self.worker.start()

    def _handle_worker_done(self, payload: dict) -> None:
        kind = payload.get("kind")
        if kind == "task_prepare":
            self._handle_task_prepare(payload)
            return
        if kind == "error":
            reply = str(payload.get("error") or "Erro local.")
        else:
            reply = str(payload.get("reply") or "Sem resposta.")
        self.status.setText("Pronto")
        self.pulse.set_mode("listening")
        if payload.get("route"):
            self._append_system(f"Rota LLM: {payload.get('route')}")
        self._append_assistant(reply)
        self._say(reply)
        self._schedule_microphone_resume()

    def _handle_task_prepare(self, payload: dict) -> None:
        spec = payload.get("spec") or {}
        sandbox = payload.get("sandbox") or {}
        if not payload.get("ok"):
            msg = f"Não aprovei a tarefa: {payload.get('error') or 'sandbox falhou'}"
            self.status.setText("Tarefa rejeitada pelo sandbox")
            self._append_assistant(msg)
            self._say(msg)
            self._schedule_microphone_resume()
            return
        dialog = ApprovalDialog(spec, sandbox, self)
        if dialog.exec_() == QDialog.Accepted:
            result = self.tasks.approve_task(spec)
            if result.get("ok"):
                msg = "Tarefa aprovada e instalada."
                self._refresh_task_list()
            else:
                msg = f"Falha ao aprovar tarefa: {result.get('error')}"
        else:
            msg = "Tarefa rejeitada."
        self.status.setText("Pronto")
        self._append_assistant(msg)
        self._say(msg)
        self._schedule_microphone_resume()

    def _refresh_task_list(self) -> None:
        self.task_list.clear()
        for task in self.tasks.list_approved():
            self.task_list.addItem(f"{task.get('name')}  |  {task.get('filename')}")

    def _append_user(self, text: str) -> None:
        self.log.appendPlainText(f"Você: {text}")

    def _append_assistant(self, text: str) -> None:
        self.log.appendPlainText(f"Ultron: {text}")

    def _append_system(self, text: str) -> None:
        self.log.appendPlainText(f"Sistema: {text}")

    def _open_config(self) -> None:
        dialog = ConfigDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return
        cfg = save_config(dialog.output_config())
        self.llm = UltronLLMClient()
        self.tasks.llm = self.llm
        cloud = cfg.get("cloud") or {}
        status = "Fallback em nuvem ativado" if cloud.get("enabled") else "Fallback em nuvem desativado"
        self._append_system(f"{status}: {provider_label(str(cloud.get('provider') or 'cloud'))}")
        self.status.setText("Config salva")

    def _accept_voice_command(self, text: str) -> bool:
        now = time.monotonic()
        if now < self._ignore_voice_until or now < self._speaking_until:
            return False
        norm = _norm_command(text)
        if not norm:
            return False
        if norm in _VOICE_FILLERS:
            return False
        if len(norm) < 5 and norm not in {"imc"}:
            return False
        words = [word for word in re.findall(r"[\wÀ-ÿ]+", norm, flags=re.UNICODE) if word not in _VOICE_FILLERS]
        if len(words) < 2 and not any(hint in norm for hint in {"imc", "status", "hora", "horas"}):
            return False
        if norm == self._last_command_norm and now - self._last_command_ts < 6.0:
            return False
        has_hint = any(hint in words or hint in norm for hint in _VOICE_COMMAND_HINTS)
        if not has_hint and len(words) < 4:
            if now - self._last_suppressed_ts > 4.0:
                self.status.setText("Ouvindo comando claro")
                self._last_suppressed_ts = now
            return False
        self._last_command_norm = norm
        self._last_command_ts = now
        return True

    def _pause_microphone(self) -> None:
        if self.recognizer and self.recognizer.isRunning():
            self.recognizer.stop()
            self.recognizer.wait(800)
            self.recognizer = None
            self.mic_button.setText("Ativar microfone")

    def _schedule_microphone_resume(self) -> None:
        if not self.gate.activated:
            return
        delay_ms = int(max(1200, min(9000, (self._speaking_until - time.monotonic()) * 1000 + 350)))
        self._ignore_voice_until = time.monotonic() + delay_ms / 1000.0
        QTimer.singleShot(delay_ms, self._start_microphone)

    def _handle_partial(self, text: str) -> None:
        if not self.gate.activated:
            self.status.setText(f"Ouvindo ativação: {text}")

    def _handle_audio_level(self, level: float) -> None:
        if time.monotonic() < self._speaking_until:
            return
        self.pulse.set_mode("listening" if self.recognizer else "locked")
        self.pulse.set_audio_level(level)

    def _say(self, text: str) -> None:
        phrase = str(text or "").strip()
        if not phrase:
            return
        self._speaking_until = time.monotonic() + max(1.2, min(9.0, len(phrase) / 15.0))
        self.pulse.set_mode("speaking")
        self.speaker.speak_async(phrase)

    def _tick_speaking_visual(self) -> None:
        if time.monotonic() >= self._speaking_until:
            if self.gate.activated:
                self.pulse.set_mode("listening")
            else:
                self.pulse.set_mode("locked")
            return
        phase = time.monotonic() * 8.0
        level = 0.35 + 0.45 * abs(math.sin(phase)) + random.random() * 0.12
        self.pulse.set_mode("speaking")
        self.pulse.set_audio_level(level)

    def closeEvent(self, event) -> None:
        if self.recognizer and self.recognizer.isRunning():
            self.recognizer.stop()
            self.recognizer.wait(1000)
        super().closeEvent(event)


def main() -> int:
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("Ultron UI")
    window = UltronWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
