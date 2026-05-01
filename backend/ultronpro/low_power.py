"""
Modo Low-Power (Paralisia Consciente / Operação Degradada)
=========================================================

Transforma a ausência de LLMs ou conectividade de 'falha de exceção' em
um estado operacional legítimo de primeira classe.
O sistema percebe sua paralisia, ajusta seu orçamento e capacidades físicas.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("uvicorn")

STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'low_power_state.json'


class LowPowerManager:
    def __init__(self):
        self.is_active = False
        self.reason = ""
        self.entered_at = 0
        self.total_time_in_low_power = 0
        self.capabilities = [
            "sandbox_execution",
            "regex_parsing",
            "db_crud",
            "local_ast_heal",
            "sleep",
        ]
        self._load_state()

    def _load_state(self):
        if STATE_PATH.exists():
            try:
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                self.is_active = data.get("is_active", False)
                self.reason = data.get("reason", "")
                self.entered_at = data.get("entered_at", 0)
                self.total_time_in_low_power = data.get("total_time_in_low_power", 0)
            except Exception:
                pass

    def _save_state(self):
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "is_active": self.is_active,
                "reason": self.reason,
                "entered_at": self.entered_at,
                "total_time_in_low_power": self.total_time_in_low_power,
            }
            STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def enter(self, reason: str):
        """Transição explícita de entrada no modo low_power."""
        if self.is_active:
            return  # Already in low power
        
        self.is_active = True
        self.reason = reason
        self.entered_at = int(time.time())
        self._save_state()

        logger.warning(f"🔋 [LOW-POWER] Entrando em Modo Operacional Degradado. Motivo: {reason}")
        
        # Broadcast the transition to the subjective global workspace
        try:
            from ultronpro import store
            store.publish_workspace(
                module="low_power_manager",
                channel="homeostasis.low_power.entered",
                payload_json=json.dumps({"reason": reason, "capabilities": self.capabilities}),
                salience=1.0,  # Max salience
                ttl_sec=3600
            )
        except Exception:
            pass
        
        # Auto-heal cognitive posture if possible
        try:
            from ultronpro import inner_monologue
            inner_monologue.think(f"Entrei em paralisia temporária (Modo Low-Power). Motivo: {reason}. Focando em heurística local.", category="reflection", source="low_power")
        except Exception:
            pass

    def exit(self, reason: str):
        """Transição explícita de saída do modo low_power."""
        if not self.is_active:
            return

        now = int(time.time())
        duration = max(0, now - self.entered_at)
        self.total_time_in_low_power += duration
        
        old_reason = self.reason
        self.is_active = False
        self.reason = ""
        self.entered_at = 0
        self._save_state()

        logger.info(f"⚡ [LOW-POWER] Saindo de Modo Degradado. Duração da paralisia: {duration}s. Retorno: {reason}")

        try:
            from ultronpro import store
            store.publish_workspace(
                module="low_power_manager",
                channel="homeostasis.low_power.exited",
                payload_json=json.dumps({"recovery_reason": reason, "duration_sec": duration, "was_caused_by": old_reason}),
                salience=0.8,
                ttl_sec=1200
            )
            from ultronpro import inner_monologue
            inner_monologue.think(f"Recuperei capacidade plena de LLMs. Saindo da paralisia após {duration} segundos.", category="reflection", source="low_power")
        except Exception:
            pass

    def get_status(self) -> dict:
        now = int(time.time())
        current_duration = max(0, now - self.entered_at) if self.is_active else 0
        return {
            "is_active": self.is_active,
            "reason": self.reason,
            "entered_at": self.entered_at,
            "current_duration_sec": current_duration,
            "total_time_in_low_power": self.total_time_in_low_power + current_duration,
            "capabilities_budget": self.capabilities if self.is_active else ["full"],
        }


# Global Singleton
_manager: LowPowerManager | None = None

def get_manager() -> LowPowerManager:
    global _manager
    if _manager is None:
        _manager = LowPowerManager()
    return _manager

def enter_mode(reason: str):
    get_manager().enter(reason)

def exit_mode(reason: str):
    get_manager().exit(reason)

def is_active() -> bool:
    return get_manager().is_active

def status() -> dict:
    return get_manager().get_status()
