"""
UltronPro Operational Memory System

Sistema de memória operacional em camadas com escopo:

1. HUMAN MEMORY (ultron.md)
   - Instruções humanas persistentes
   - Regras, convenções, preferências
   - Não é sobrescrito pelo sistema

2. LEARNED MEMORY (ultron.learned.md)
   - Aprendizados descobertos pelo sistema
   - Comandos válidos, invariantes, benchmarks
   - Pode ser enriquecido automaticamente

3. AUTO MEMORY (auto_memory.jsonl)
   - Memória automática com escopo
   - project: por diretório de projeto
   - environment: por ambiente (dev/prod)
   - sandbox: por sandbox isolado
   - Session: por sessão de uso

Estrutura de diretórios:
.ultron/
  memory/
    global/           # Memória global (todos os projetos)
      ultron.md
      ultron.learned.md
      auto_memory.jsonl
    project/{sha}/    # Por projeto (hash do path)
      ultron.md
      ultron.learned.md
      auto_memory.jsonl
    env/{name}/       # Por ambiente
      ultron.md
      ultron.learned.md
      auto_memory.jsonl
    sandbox/{id}/     # Por sandbox
      ultron.md
      ultron.learned.md
      auto_memory.jsonl
"""

import os
import re
import json
import time
import hashlib
import asyncio
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from datetime import datetime


class MemoryScope(str, Enum):
    """Escopos de memória."""
    GLOBAL = "global"      # Memória global
    PROJECT = "project"    # Por projeto
    ENVIRONMENT = "env"    # Por ambiente
    SANDBOX = "sandbox"    # Por sandbox
    SESSION = "session"    # Por sessão


class MemoryLayer(str, Enum):
    """Camadas de memória."""
    HUMAN = "human"       # Instruções humanas
    LEARNED = "learned"   # Aprendizados do sistema
    AUTO = "auto"        # Memória automática


@dataclass
class MemoryEntry:
    """Entrada de memória."""
    id: str
    scope: MemoryScope
    layer: MemoryLayer
    content: str
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    source: str = "system"  # human, system, auto
    confidence: float = 1.0
    access_count: int = 0
    last_access: Optional[float] = None
    
    def touch(self):
        """Atualiza timestamp de acesso."""
        self.access_count += 1
        self.last_access = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope.value,
            "layer": self.layer.value,
            "content": self.content,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "confidence": self.confidence,
            "access_count": self.access_count,
            "last_access": self.last_access,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            id=d["id"],
            scope=MemoryScope(d["scope"]),
            layer=MemoryLayer(d["layer"]),
            content=d["content"],
            tags=d.get("tags", []),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            source=d.get("source", "system"),
            confidence=d.get("confidence", 1.0),
            access_count=d.get("access_count", 0),
            last_access=d.get("last_access"),
        )


@dataclass
class MemoryContext:
    """Contexto de memória para uma sessão."""
    project_path: Optional[str] = None
    environment: str = "default"
    sandbox_id: Optional[str] = None
    session_id: str = ""
    
    @property
    def project_hash(self) -> str:
        if not self.project_path:
            return "default"
        return hashlib.md5(os.path.abspath(self.project_path).encode()).hexdigest()[:12]
    
    def get_scope_path(self, scope: MemoryScope, base_path: Optional[Path] = None) -> Path:
        """Retorna path para um escopo específico."""
        if base_path is None:
            base_path = self._get_memory_root()
        
        if scope == MemoryScope.GLOBAL:
            return base_path / "global"
        elif scope == MemoryScope.PROJECT:
            return base_path / "project" / self.project_hash
        elif scope == MemoryScope.ENVIRONMENT:
            return base_path / "env" / self.environment
        elif scope == MemoryScope.SANDBOX:
            safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', self.sandbox_id or "default")
            return base_path / "sandbox" / safe_id
        elif scope == MemoryScope.SESSION:
            return base_path / "session" / self.session_id
        
        return base_path / "global"
    
    def _get_memory_root(self) -> Path:
        """Retorna raiz da memória (.ultron/memory)."""
        if self.project_path:
            project_root = Path(self.project_path).resolve()
            return project_root / ".ultron" / "memory"
        
        cwd = Path.cwd()
        return cwd / ".ultron" / "memory"


class OperationalMemory:
    """
    Sistema de memória operacional em camadas.
    
    Funcionalidades:
    1. Ler/escrever em cada camada
    2. Carregar memória por escopo
    3. Query com relevância
    4. Session start/end hooks
    """
    
    def __init__(self, context: Optional[MemoryContext] = None):
        self.context = context or MemoryContext()
        self._entries: Dict[str, List[MemoryEntry]] = {
            MemoryScope.GLOBAL: [],
            MemoryScope.PROJECT: [],
            MemoryScope.ENVIRONMENT: [],
            MemoryScope.SANDBOX: [],
            MemoryScope.SESSION: [],
        }
        self._loaded = False
    
    # ==================== FILE PATHS ====================
    
    def _get_memory_file(self, scope: MemoryScope, layer: MemoryLayer) -> Path:
        """Retorna path do arquivo de memória."""
        scope_path = self.context.get_scope_path(scope)
        scope_path.mkdir(parents=True, exist_ok=True)
        
        if layer == MemoryLayer.HUMAN:
            return scope_path / "ultron.md"
        elif layer == MemoryLayer.LEARNED:
            return scope_path / "ultron.learned.md"
        elif layer == MemoryLayer.AUTO:
            return scope_path / "auto_memory.jsonl"
        
        return scope_path / "memory.jsonl"
    
    # ==================== READ ====================
    
    def read_human_memory(self, scope: MemoryScope = MemoryScope.GLOBAL) -> str:
        """Lê memória humana de um escopo."""
        path = self._get_memory_file(scope, MemoryLayer.HUMAN)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
    
    def read_learned_memory(self, scope: MemoryScope = MemoryScope.GLOBAL) -> str:
        """Lê memória de aprendizados de um escopo."""
        path = self._get_memory_file(scope, MemoryLayer.LEARNED)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""
    
    def read_auto_memory(
        self,
        scope: MemoryScope = MemoryScope.GLOBAL,
        tags: Optional[List[str]] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[MemoryEntry]:
        """Lê entradas de memória automática."""
        path = self._get_memory_file(scope, MemoryLayer.AUTO)
        entries = []
        
        if not path.exists():
            return entries
        
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        entry = MemoryEntry.from_dict(d)
                        
                        if tags and not any(t in entry.tags for t in tags):
                            continue
                        if since and entry.created_at < since:
                            continue
                        
                        entries.append(entry)
                    except:
                        continue
        except Exception:
            pass
        
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]
    
    # ==================== WRITE ====================
    
    def write_human_memory(
        self,
        content: str,
        scope: MemoryScope = MemoryScope.GLOBAL,
        append: bool = False,
    ) -> bool:
        """Escreve memória humana (não sobrescreve aprendizados)."""
        path = self._get_memory_file(scope, MemoryLayer.HUMAN)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            if append and path.exists():
                existing = path.read_text(encoding="utf-8")
                content = existing + "\n" + content
            
            path.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False
    
    def write_learned_memory(
        self,
        content: str,
        scope: MemoryScope = MemoryScope.GLOBAL,
        tags: Optional[List[str]] = None,
        source: str = "system",
    ) -> bool:
        """Escreve aprendizado descoberto pelo sistema."""
        path = self._get_memory_file(scope, MemoryLayer.LEARNED)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag_str = ", ".join(tags) if tags else "general"
        
        entry = f"\n## Learned [{timestamp}] (tags: {tag_str})\n{content}\n"
        
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(entry)
            return True
        except Exception:
            return False
    
    def add_auto_entry(
        self,
        content: str,
        layer: MemoryLayer = MemoryLayer.AUTO,
        tags: Optional[List[str]] = None,
        scope: Optional[MemoryScope] = None,
        source: str = "auto",
        confidence: float = 1.0,
    ) -> Optional[str]:
        """Adiciona entrada de memória automática."""
        scope = scope or MemoryScope.PROJECT
        path = self._get_memory_file(scope, layer)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        entry_id = hashlib.md5(f"{content}{time.time()}".encode()).hexdigest()[:16]
        
        entry = MemoryEntry(
            id=entry_id,
            scope=scope,
            layer=layer,
            content=content,
            tags=tags or [],
            source=source,
            confidence=confidence,
        )
        
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            return entry_id
        except Exception:
            return None
    
    # ==================== SESSION LIFECYCLE ====================
    
    def session_start(self) -> Dict[str, Any]:
        """Carrega memória no início de uma sessão."""
        if not self.context.session_id:
            self.context.session_id = hashlib.md5(str(time.time()).encode()).hexdigest()[:12]
        
        self._loaded = True
        loaded = {}
        
        for scope in MemoryScope:
            human = self.read_human_memory(scope)
            learned = self.read_learned_memory(scope)
            auto = self.read_auto_memory(scope, limit=50)
            
            if human or learned or auto:
                loaded[scope.value] = {
                    "human": human,
                    "learned": learned,
                    "auto_count": len(auto),
                }
        
        return {
            "session_id": self.context.session_id,
            "context": {
                "project": self.context.project_path,
                "project_hash": self.context.project_hash,
                "environment": self.context.environment,
                "sandbox": self.context.sandbox_id,
            },
            "loaded": loaded,
            "timestamp": time.time(),
        }
    
    def session_end(self) -> Dict[str, Any]:
        """Finaliza sessão e persiste aprendizados."""
        self._loaded = False
        
        return {
            "session_id": self.context.session_id,
            "timestamp": time.time(),
            "status": "ended",
        }
    
    # ==================== QUERY ====================
    
    def query(
        self,
        text: str,
        scopes: Optional[List[MemoryScope]] = None,
        layers: Optional[List[MemoryLayer]] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Busca memória por texto/tags."""
        scopes = scopes or list(MemoryScope)
        layers = layers or list(MemoryLayer)
        
        results = []
        text_lower = text.lower()
        text_words = set(re.findall(r'\w{3,}', text_lower))
        
        for scope in scopes:
            if MemoryLayer.HUMAN in layers:
                human = self.read_human_memory(scope)
                if human and self._relevance_score(human, text_lower, text_words) > 0.3:
                    results.append({
                        "type": "human",
                        "scope": scope.value,
                        "content": human[:2000],
                        "score": self._relevance_score(human, text_lower, text_words),
                    })
            
            if MemoryLayer.LEARNED in layers:
                learned = self.read_learned_memory(scope)
                if learned and self._relevance_score(learned, text_lower, text_words) > 0.3:
                    results.append({
                        "type": "learned",
                        "scope": scope.value,
                        "content": learned[:2000],
                        "score": self._relevance_score(learned, text_lower, text_words),
                    })
            
            if MemoryLayer.AUTO in layers:
                auto_entries = self.read_auto_memory(scope, tags=tags, limit=limit)
                for entry in auto_entries:
                    score = self._relevance_score(entry.content, text_lower, text_words)
                    if score > 0.3:
                        entry.touch()
                        results.append({
                            "type": "auto",
                            "scope": scope.value,
                            "content": entry.content,
                            "tags": entry.tags,
                            "score": score,
                            "entry": entry.to_dict(),
                        })
        
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]
    
    def _relevance_score(self, content: str, query_lower: str, query_words: Set[str]) -> float:
        """Calcula score de relevância."""
        content_lower = content.lower()
        
        if query_lower in content_lower:
            return 1.0
        
        score = 0.0
        content_words = set(re.findall(r'\w{3,}', content_lower))
        
        overlap = query_words & content_words
        if overlap:
            score += len(overlap) / max(len(query_words), 1) * 0.8
        
        if any(word in content_lower for word in query_words):
            score += 0.2
        
        return min(score, 1.0)
    
    # ==================== LEARN ====================
    
    def learn(
        self,
        content: str,
        category: str = "general",
        scope: Optional[MemoryScope] = None,
    ) -> bool:
        """Registra aprendizado do sistema."""
        scope = scope or MemoryScope.PROJECT
        
        lines = content.strip().split("\n")
        formatted = "\n".join(f"- {line.strip()}" for line in lines if line.strip())
        
        return self.write_learned_memory(
            content=f"\n### {category}\n{formatted}",
            scope=scope,
            tags=[category],
            source="system",
        )
    
    def learn_command(
        self,
        command: str,
        working_dir: Optional[str] = None,
        success: bool = True,
        output: Optional[str] = None,
    ) -> Optional[str]:
        """Registra comando válido aprendido."""
        entry_content = f"Command: `{command}`"
        if working_dir:
            entry_content += f"\nWorking dir: `{working_dir}`"
        entry_content += f"\nSuccess: {success}"
        if output:
            snippet = output[:200].replace("\n", " ")
            entry_content += f"\nOutput snippet: {snippet}..."
        
        tags = ["command", "bash"]
        if success:
            tags.append("verified")
        else:
            tags.append("failed")
        
        return self.add_auto_entry(
            content=entry_content,
            layer=MemoryLayer.AUTO,
            tags=tags,
            scope=MemoryScope.PROJECT,
            source="command_execution",
            confidence=0.8 if success else 0.5,
        )
    
    def learn_benchmark(
        self,
        name: str,
        metrics: Dict[str, Any],
        threshold: Optional[float] = None,
    ) -> bool:
        """Registra benchmark aprendido."""
        content = f"Benchmark: {name}\n"
        content += "Metrics:\n"
        for k, v in metrics.items():
            content += f"  - {k}: {v}\n"
        if threshold:
            content += f"Threshold: {threshold}\n"
        
        return self.write_learned_memory(
            content=content,
            scope=MemoryScope.PROJECT,
            tags=["benchmark", name],
            source="system",
        )
    
    def learn_invariant(
        self,
        pattern: str,
        reason: str,
        examples: Optional[List[str]] = None,
    ) -> bool:
        """Registra invariante descoberta."""
        content = f"Pattern: `{pattern}`\n"
        content += f"Reason: {reason}\n"
        if examples:
            content += "Examples:\n"
            for ex in examples[:5]:
                content += f"  - `{ex}`\n"
        
        return self.write_learned_memory(
            content=content,
            scope=MemoryScope.PROJECT,
            tags=["invariant", "pattern"],
            source="discovery",
        )
    
    # ==================== BUILD CONTEXT ====================
    
    def build_session_context(
        self,
        max_chars: int = 8000,
        include_layers: Optional[List[MemoryLayer]] = None,
    ) -> str:
        """Constrói contexto de memória para uma sessão."""
        include_layers = include_layers or [MemoryLayer.HUMAN, MemoryLayer.LEARNED]
        
        parts = []
        total_chars = 0
        
        priority_scopes = [
            MemoryScope.PROJECT,
            MemoryScope.ENVIRONMENT,
            MemoryScope.SANDBOX,
            MemoryScope.GLOBAL,
        ]
        
        for scope in priority_scopes:
            if total_chars >= max_chars:
                break
            
            scope_parts = []
            
            if MemoryLayer.HUMAN in include_layers:
                human = self.read_human_memory(scope)
                if human:
                    scope_parts.append(f"### Human Memory ({scope.value})\n{human}")
            
            if MemoryLayer.LEARNED in include_layers:
                learned = self.read_learned_memory(scope)
                if learned:
                    scope_parts.append(f"### Learned Memory ({scope.value})\n{learned}")
            
            if scope_parts:
                scope_text = "\n\n".join(scope_parts)
                if total_chars + len(scope_text) <= max_chars:
                    parts.append(scope_text)
                    total_chars += len(scope_text)
                else:
                    remaining = max_chars - total_chars
                    parts.append(scope_text[:remaining])
                    break
        
        if parts:
            return "# Operational Memory\n\n" + "\n\n---\n\n".join(parts)
        
        return ""
    
    # ==================== MAINTENANCE ====================
    
    def prune_auto_memory(
        self,
        scope: MemoryScope = MemoryScope.GLOBAL,
        max_entries: int = 1000,
        older_than_days: int = 30,
    ) -> Dict[str, Any]:
        """Remove entradas antigas de memória automática."""
        path = self._get_memory_file(scope, MemoryLayer.AUTO)
        if not path.exists():
            return {"pruned": 0, "remaining": 0}
        
        cutoff = time.time() - (older_than_days * 86400)
        entries = []
        pruned = 0
        
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get("created_at", 0) < cutoff:
                            pruned += 1
                            continue
                        entries.append(line)
                    except:
                        pruned += 1
            
            entries = entries[-max_entries:]
            
            with path.open("w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(entry + "\n")
            
            return {
                "pruned": pruned,
                "remaining": len(entries),
                "path": str(path),
            }
        except Exception as e:
            return {"error": str(e), "pruned": 0, "remaining": 0}
    
    def get_stats(self, scope: Optional[MemoryScope] = None) -> Dict[str, Any]:
        """Retorna estatísticas de memória."""
        scopes = [scope] if scope else list(MemoryScope)
        
        stats = {}
        for s in scopes:
            human = self.read_human_memory(s)
            learned = self.read_learned_memory(s)
            auto = self.read_auto_memory(s, limit=10000)
            
            stats[s.value] = {
                "human_chars": len(human),
                "learned_chars": len(learned),
                "auto_entries": len(auto),
                "scope_path": str(self._get_memory_file(s, MemoryLayer.HUMAN).parent),
            }
        
        return stats


# ==================== GLOBAL INSTANCE ====================

_memory: Optional[OperationalMemory] = None

def get_operational_memory(
    project_path: Optional[str] = None,
    environment: str = "default",
    sandbox_id: Optional[str] = None,
) -> OperationalMemory:
    """Retorna instância de memória operacional."""
    global _memory
    
    context = MemoryContext(
        project_path=project_path,
        environment=environment,
        sandbox_id=sandbox_id,
    )
    
    _memory = OperationalMemory(context)
    return _memory


def init_session(
    project_path: Optional[str] = None,
    environment: str = "default",
) -> Dict[str, Any]:
    """Inicializa memória para uma sessão."""
    mem = get_operational_memory(
        project_path=project_path,
        environment=environment,
    )
    return mem.session_start()


def end_session() -> Dict[str, Any]:
    """Finaliza sessão de memória."""
    global _memory
    if _memory:
        return _memory.session_end()
    return {"status": "no_session"}


def learn(content: str, category: str = "general") -> bool:
    """Registra aprendizado (atalho)."""
    global _memory
    if _memory:
        return _memory.learn(content, category)
    return False


def query_memory(text: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Busca memória (atalho)."""
    global _memory
    if _memory:
        return _memory.query(text, limit=limit)
    return []
