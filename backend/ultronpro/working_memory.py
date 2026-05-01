"""
Working Memory Buffer — Memória de Trabalho Ativa
==================================================

Sistema de memória de trabalho que persiste entre requests e suporta
mecanismo de atenção por saliência para filtrar informação relevante.

Características:
- Buffer circular com capacidade limitada
- Scoring de saliência para cada item
- Decay temporal dos itens
- Atenção seletiva (foco em itens de alta saliência)
- Persistência em disco

"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Any, Optional
from collections import deque
from enum import Enum

DATA_DIR = Path(__file__).resolve().parent.parent.parent / 'data'
WORKING_MEMORY_PATH = DATA_DIR / 'working_memory.json'


class AttentionState(Enum):
    FOCUSED = "focused"
    DISTRACTED = "distracted"
    DEEP = "deep"
    BROAD = "broad"


@dataclass
class WorkingMemoryItem:
    id: str
    content: str
    salience: float
    created_at: int
    last_accessed: int
    access_count: int
    attention_level: float
    source: str
    item_type: str
    metadata: dict = field(default_factory=dict)


@dataclass
class WorkingMemoryState:
    items: list[dict]
    focus_item_id: Optional[str]
    attention_state: str
    attention_breadth: float
    cognitive_load: float
    capacity_used: float
    max_capacity: int
    updated_at: int


class WorkingMemory:
    MAX_CAPACITY = 50
    DEFAULT_SALIENCE = 0.5
    DECAY_RATE = 0.95
    ATTENTION_DECAY = 0.98
    FOCUS_BOOST = 1.5

    def __init__(self, max_capacity: int = MAX_CAPACITY):
        self.max_capacity = max_capacity
        self.items: deque[WorkingMemoryItem] = deque(maxlen=max_capacity)
        self.focus_item_id: Optional[str] = None
        self.attention_state = AttentionState.BROAD
        self.attention_breadth = 0.5
        self.cognitive_load = 0.0
        self._load()

    def _load(self):
        if not WORKING_MEMORY_PATH.exists():
            return
        try:
            data = json.loads(WORKING_MEMORY_PATH.read_text(encoding='utf-8'))
            self.max_capacity = data.get('max_capacity', self.MAX_CAPACITY)
            self.attention_state = AttentionState(data.get('attention_state', 'broad'))
            self.attention_breadth = data.get('attention_breadth', 0.5)
            self.focus_item_id = data.get('focus_item_id')
            self.items = deque(
                [WorkingMemoryItem(**item) for item in data.get('items', [])],
                maxlen=self.max_capacity
            )
        except Exception:
            pass

    def _save(self):
        data = {
            'items': [asdict(item) for item in self.items],
            'focus_item_id': self.focus_item_id,
            'attention_state': self.attention_state.value,
            'attention_breadth': self.attention_breadth,
            'max_capacity': self.max_capacity,
            'updated_at': int(time.time()),
        }
        WORKING_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        WORKING_MEMORY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _compute_salience(self, content: str, source: str, item_type: str) -> float:
        base = self.DEFAULT_SALIENCE
        
        if item_type == 'goal':
            base += 0.2
        elif item_type == 'error':
            base += 0.15
        elif item_type == 'success':
            base += 0.1
        elif item_type == 'question':
            base += 0.1
        
        if source == 'user':
            base += 0.15
        elif source == 'self':
            base += 0.1
        elif source == 'system':
            base += 0.05
        
        content_lower = content.lower()
        urgency_keywords = ['urgent', 'immediately', 'now', 'critical', 'emergency', 'importante', 'urgente', 'agora']
        for kw in urgency_keywords:
            if kw in content_lower:
                base += 0.1
                break
        
        return min(1.0, base)

    def add(self, content: str, source: str = 'system', item_type: str = 'observation',
            salience: float | None = None, metadata: dict | None = None) -> WorkingMemoryItem:
        if salience is None:
            salience = self._compute_salience(content, source, item_type)
        
        now = int(time.time())
        item = WorkingMemoryItem(
            id=f"wm_{now}_{uuid.uuid4().hex[:6]}",
            content=content[:500],
            salience=salience,
            created_at=now,
            last_accessed=now,
            access_count=0,
            attention_level=1.0,
            source=source,
            item_type=item_type,
            metadata=metadata or {},
        )
        
        if self.focus_item_id:
            for existing in self.items:
                if existing.id == self.focus_item_id:
                    existing.salience *= self.FOCUS_BOOST
                    break
        
        self.items.append(item)
        self._save()
        return item

    def access(self, item_id: str) -> Optional[WorkingMemoryItem]:
        now = int(time.time())
        for item in self.items:
            if item.id == item_id:
                item.last_accessed = now
                item.access_count += 1
                item.attention_level = min(1.0, item.attention_level + 0.1)
                self.focus_item_id = item_id
                self._save()
                return item
        return None

    def get_focused(self) -> Optional[WorkingMemoryItem]:
        if not self.focus_item_id:
            return None
        for item in self.items:
            if item.id == self.focus_item_id:
                return item
        return None

    def get_top(self, n: int = 10, min_salience: float = 0.0) -> list[WorkingMemoryItem]:
        self._apply_decay()
        sorted_items = sorted(self.items, key=lambda x: x.salience, reverse=True)
        return [item for item in sorted_items if item.salience >= min_salience][:n]

    def get_context_window(self, max_tokens: int = 2000) -> str:
        items = self.get_top(n=self.max_capacity)
        context_parts = []
        current_len = 0
        
        for item in items:
            item_len = len(item.content) + 20
            if current_len + item_len > max_tokens:
                break
            prefix = ">> " if item.id == self.focus_item_id else "> "
            context_parts.append(f"{prefix}[{item.item_type}] {item.content}")
            current_len += item_len
        
        return "\n".join(context_parts)

    def _apply_decay(self):
        now = int(time.time())
        for item in self.items:
            age_seconds = now - item.created_at
            age_minutes = age_seconds / 60
            
            time_decay = pow(self.DECAY_RATE, age_minutes / 10)
            attention_decay = pow(self.ATTENTION_DECAY, item.access_count)
            
            item.salience = item.salience * time_decay * attention_decay
            item.salience = max(0.05, item.salience)

    def set_attention_state(self, state: AttentionState | str):
        if isinstance(state, str):
            state = AttentionState(state)
        self.attention_state = state
        
        if state == AttentionState.FOCUSED:
            self.attention_breadth = 0.3
        elif state == AttentionState.DISTRACTED:
            self.attention_breadth = 0.9
        elif state == AttentionState.DEEP:
            self.attention_breadth = 0.2
        elif state == AttentionState.BROAD:
            self.attention_breadth = 0.7
        
        self._save()

    def set_focus(self, item_id: str | None):
        if item_id is None:
            self.focus_item_id = None
            self._save()
            return
        
        for item in self.items:
            if item.id == item_id:
                self.focus_item_id = item_id
                item.salience = min(1.0, item.salience * self.FOCUS_BOOST)
                break
        self._save()

    def clear(self, item_type: str | None = None):
        if item_type is None:
            self.items.clear()
            self.focus_item_id = None
        else:
            self.items = deque(
                [item for item in self.items if item.item_type != item_type],
                maxlen=self.max_capacity
            )
        self._save()

    def get_status(self) -> dict:
        self._apply_decay()
        total_salience = sum(item.salience for item in self.items)
        return {
            'item_count': len(self.items),
            'max_capacity': self.max_capacity,
            'capacity_used': len(self.items) / self.max_capacity,
            'cognitive_load': self.cognitive_load,
            'attention_state': self.attention_state.value,
            'attention_breadth': round(self.attention_breadth, 2),
            'focused_item': self.get_focused().content[:80] if self.get_focused() else None,
            'avg_salience': round(total_salience / max(1, len(self.items)), 3),
            'top_items': [
                {'id': item.id, 'content': item.content[:60], 'salience': round(item.salience, 2), 'type': item.item_type}
                for item in self.get_top(5)
            ],
        }


_working_memory: Optional[WorkingMemory] = None


def get_working_memory() -> WorkingMemory:
    global _working_memory
    if _working_memory is None:
        _working_memory = WorkingMemory()
    return _working_memory


def add_to_working_memory(content: str, source: str = 'system', item_type: str = 'observation',
                          salience: float | None = None, metadata: dict | None = None) -> WorkingMemoryItem:
    return get_working_memory().add(content, source, item_type, salience, metadata)


def access_working_memory(item_id: str) -> Optional[WorkingMemoryItem]:
    return get_working_memory().access(item_id)


def get_working_memory_context(max_tokens: int = 2000) -> str:
    return get_working_memory().get_context_window(max_tokens)


def get_working_memory_status() -> dict:
    return get_working_memory().get_status()


def set_attention_state(state: str):
    get_working_memory().set_attention_state(state)


def clear_working_memory(item_type: str | None = None):
    get_working_memory().clear(item_type)
