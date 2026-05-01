"""
UltronPro Skill System - Carregador de Skills

Sistema de skills reutilizáveis para o UltronPro.
Skills são pacotes de capacidades recorrentes que podem ser
carregados, configurados e executados pelo motor autônomo.
"""

import os
import json
import logging
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

try:
    import yaml
except Exception:  # PyYAML is optional at runtime; a small parser covers local skill metadata.
    yaml = None

logger = logging.getLogger("uvicorn")

# Caminho base dos skills
SKILLS_DIR = Path(__file__).resolve().parent.parent / 'ultron_skills'


@dataclass
class Skill:
    """Representa um skill carregado."""
    name: str
    path: Path
    description: str
    allowed_tools: List[str] = field(default_factory=list)
    budget: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = 'low'
    when_to_use: str = ''
    skill_path: str = ''
    subagent: Optional[str] = None
    hooks: Dict[str, str] = field(default_factory=dict)
    success_checks: List[str] = field(default_factory=list)
    content: str = ''
    version: str = '1.0.0'
    author: str = 'system'
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    _raw_frontmatter: Dict[str, Any] = field(default_factory=dict)
    
    def get_budget_limit(self) -> int:
        """Retorna limite de budget em segundos."""
        return self.budget.get('max_seconds', 60)
    
    def get_risk_score(self) -> float:
        """Retorna score de risco (0.0 a 1.0)."""
        risk_scores = {'low': 0.1, 'medium': 0.5, 'high': 0.8, 'critical': 1.0}
        return risk_scores.get(self.risk_level, 0.5)
    
    def is_safe_to_run(self, current_budget: float = 0) -> bool:
        """Verifica se é seguro executar."""
        if not self.enabled:
            return False
        if self.get_risk_score() > 0.7 and current_budget > 0:
            return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Serializa skill para dict."""
        return {
            'name': self.name,
            'description': self.description,
            'allowed_tools': self.allowed_tools,
            'budget': self.budget,
            'risk_level': self.risk_level,
            'when_to_use': self.when_to_use,
            'path': self.skill_path,
            'subagent': self.subagent,
            'hooks': self.hooks,
            'success_checks': self.success_checks,
            'version': self.version,
            'author': self.author,
            'tags': self.tags,
            'enabled': self.enabled,
        }


class SkillLoader:
    """Carregador e gerenciador de skills."""
    
    def __init__(self, skills_dir: Optional[Path] = None):
        self.skills_dir = skills_dir or SKILLS_DIR
        self._skills: Dict[str, Skill] = {}
        self._skill_index: Dict[str, List[str]] = {}  # tag -> skill names
        self._loaded = False

    def _parse_scalar(self, value: str) -> Any:
        value = value.strip()
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        try:
            if re.fullmatch(r'-?\d+', value):
                return int(value)
            if re.fullmatch(r'-?\d+\.\d+', value):
                return float(value)
        except Exception:
            pass
        return value.strip('"\'')

    def _parse_frontmatter_fallback(self, fm_text: str) -> Dict[str, Any]:
        """Parser mínimo para o frontmatter usado pelos SKILL.md locais."""
        data: Dict[str, Any] = {}
        lines = fm_text.splitlines()
        i = 0
        while i < len(lines):
            raw = lines[i]
            if not raw.strip() or raw.lstrip().startswith('#') or raw.startswith(' '):
                i += 1
                continue
            if ':' not in raw:
                i += 1
                continue
            key, value = raw.split(':', 1)
            key = key.strip()
            value = value.strip()
            if value == '|':
                block: list[str] = []
                i += 1
                while i < len(lines) and (lines[i].startswith(' ') or not lines[i].strip()):
                    block.append(lines[i][2:] if lines[i].startswith('  ') else lines[i].strip())
                    i += 1
                data[key] = '\n'.join(block).rstrip()
                continue
            if value:
                data[key] = self._parse_scalar(value)
                i += 1
                continue

            nested: list[str] = []
            i += 1
            while i < len(lines) and (lines[i].startswith(' ') or not lines[i].strip()):
                if lines[i].strip():
                    nested.append(lines[i])
                i += 1
            stripped = [x.strip() for x in nested]
            if all(x.startswith('- ') for x in stripped):
                data[key] = [self._parse_scalar(x[2:].strip()) for x in stripped]
            else:
                obj: Dict[str, Any] = {}
                for item in stripped:
                    if ':' in item:
                        k, v = item.split(':', 1)
                        obj[k.strip()] = self._parse_scalar(v.strip())
                data[key] = obj
        return data
    
    def _parse_frontmatter(self, content: str) -> tuple[Dict[str, Any], str]:
        """Extrai frontmatter YAML e conteúdo Markdown."""
        fm_pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(fm_pattern, content, re.DOTALL)
        
        if match:
            fm_text = match.group(1)
            md_content = match.group(2)
            try:
                if yaml:
                    frontmatter = yaml.safe_load(fm_text) or {}
                else:
                    frontmatter = self._parse_frontmatter_fallback(fm_text)
            except Exception as e:
                logger.warning(f"Skill frontmatter parse error: {e}")
                frontmatter = {}
            return frontmatter, md_content
        
        return {}, content
    
    def _extract_description(self, content: str) -> str:
        """Extrai descrição do conteúdo Markdown (primeiro parágrafo)."""
        lines = content.strip().split('\n')
        desc_lines = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('- '):
                break
            desc_lines.append(line)
            if len(desc_lines) >= 2:
                break
        
        return ' '.join(desc_lines)[:200] if desc_lines else 'No description'
    
    def load_skill(self, skill_path: Path) -> Optional[Skill]:
        """Carrega um skill de um arquivo SKILL.md."""
        try:
            if not skill_path.exists():
                return None
            
            content = skill_path.read_text(encoding='utf-8')
            frontmatter, md_content = self._parse_frontmatter(content)
            
            if not frontmatter:
                logger.warning(f"Skill {skill_path.name} has no frontmatter")
                return None
            
            # Nome do skill vem do diretório
            skill_name = skill_path.parent.name
            
            # Campos obrigatórios mínimos
            if 'path' not in frontmatter and 'subagent' not in frontmatter:
                logger.warning(f"Skill {skill_name} has no path or subagent")
                return None
            
            skill = Skill(
                name=skill_name,
                path=skill_path,
                description=frontmatter.get('description', self._extract_description(md_content)),
                allowed_tools=frontmatter.get('allowed_tools', []),
                budget=frontmatter.get('budget', {}),
                risk_level=frontmatter.get('risk_level', 'low'),
                when_to_use=frontmatter.get('when_to_use', ''),
                skill_path=frontmatter.get('path', ''),
                subagent=frontmatter.get('subagent'),
                hooks=frontmatter.get('hooks', {}),
                success_checks=frontmatter.get('success_checks', []),
                content=md_content.strip(),
                version=frontmatter.get('version', '1.0.0'),
                author=frontmatter.get('author', 'system'),
                tags=frontmatter.get('tags', []),
                enabled=frontmatter.get('enabled', True),
                _raw_frontmatter=frontmatter,
            )
            
            logger.info(f"Loaded skill: {skill_name} (risk={skill.risk_level}, tools={len(skill.allowed_tools)})")
            return skill
            
        except Exception as e:
            logger.error(f"Error loading skill {skill_path}: {e}")
            return None
    
    def load_all(self, force: bool = False) -> Dict[str, Skill]:
        """Carrega todos os skills do diretório."""
        if self._loaded and not force:
            return self._skills
        
        self._skills.clear()
        self._skill_index.clear()
        
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return self._skills
        
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            
            skill_file = skill_dir / 'SKILL.md'
            if not skill_file.exists():
                continue
            
            skill = self.load_skill(skill_file)
            if skill:
                self._skills[skill.name] = skill
                
                # Index por tags
                for tag in skill.tags:
                    if tag not in self._skill_index:
                        self._skill_index[tag] = []
                    self._skill_index[tag].append(skill.name)
        
        self._loaded = True
        logger.info(f"Loaded {len(self._skills)} skills")
        return self._skills
    
    def get_skill(self, name: str) -> Optional[Skill]:
        """Retorna skill pelo nome."""
        if not self._loaded:
            self.load_all()
        return self._skills.get(name)
    
    def find_skills(self, query: str, tags: Optional[List[str]] = None, 
                   risk_level: Optional[str] = None) -> List[Skill]:
        """Busca skills por query, tags ou nível de risco."""
        if not self._loaded:
            self.load_all()
        
        results = list(self._skills.values())
        
        # Filtrar por tags
        if tags:
            matching_names = set()
            for tag in tags:
                matching_names.update(self._skill_index.get(tag, []))
            results = [s for s in results if s.name in matching_names]
        
        # Filtrar por risco
        if risk_level:
            results = [s for s in results if s.risk_level == risk_level]
        
        # Filtrar por query (quando usar, descrição, name)
        if query:
            query_lower = query.lower()
            query_words = set(query_lower.replace(' ', '').split())
            scored = []
            for s in results:
                score = 0
                
                # Verificar quando_usar
                when_lower = s.when_to_use.lower()
                if query_lower in when_lower:
                    score += 10
                
                # Verificar descrição
                if query_lower in s.description.lower():
                    score += 5
                
                # Verificar nome do skill
                if query_lower in s.name.lower():
                    score += 8
                
                # Verificar tags (busca parcial)
                for tag in s.tags:
                    tag_lower = tag.lower()
                    if tag_lower in query_lower or query_lower in tag_lower:
                        score += 4
                    # Buscar por palavra chave parcial
                    for word in query_words:
                        if len(word) > 3 and word in tag_lower.replace('_', ''):
                            score += 2
                
                # Verificar path
                if query_lower in s.skill_path.lower():
                    score += 3
                
                if score > 0:
                    scored.append((score, s))
            
            scored.sort(reverse=True)
            results = [s for _, s in scored]
        
        return results
    
    def suggest_skill(self, task: str) -> Optional[Skill]:
        """Sugere o melhor skill para uma tarefa."""
        if not self._loaded:
            self.load_all()

        try:
            from ultronpro.core.intent import is_external_factual_intent

            web_skill = self._skills.get('web_search')
            if web_skill and web_skill.enabled and is_external_factual_intent(task):
                return web_skill
        except Exception:
            pass
        
        # Extrair palavras-chave da tarefa
        task_words = set(re.findall(r'\b\w{4,}\b', task.lower()))
        
        scored = []
        for name, s in self._skills.items():
            if not s.enabled:
                continue
            
            score = 0
            
            # Verificar correspondência direta no nome
            name_lower = name.lower()
            task_lower = task.lower()
            if name_lower in task_lower or task_lower in name_lower:
                score += 20
            
            # Verificar correspondência nas tags
            for tag in s.tags:
                tag_clean = tag.lower().replace('_', '')
                if tag_clean in task_lower:
                    score += 10
                for word in task_words:
                    if word in tag_clean:
                        score += 5
            
            # Verificar quando_usar
            when_lower = s.when_to_use.lower()
            for word in task_words:
                if word in when_lower:
                    score += 3
            
            # Bonus para skills de baixo risco
            if s.risk_level == 'low':
                score *= 1.1
            elif s.risk_level == 'medium':
                score *= 1.0
            
            if score > 0:
                scored.append((score, s))
        
        if scored:
            scored.sort(reverse=True)
            return scored[0][1]
        
        return None
    
    def get_enabled_skills(self) -> List[Skill]:
        """Retorna todos os skills habilitados."""
        if not self._loaded:
            self.load_all()
        return [s for s in self._skills.values() if s.enabled]
    
    def get_by_tool(self, tool: str) -> List[Skill]:
        """Retorna skills que usam uma ferramenta específica."""
        if not self._loaded:
            self.load_all()
        return [s for s in self._skills.values() if tool in s.allowed_tools]
    
    def get_status(self) -> Dict[str, Any]:
        """Retorna status dos skills."""
        if not self._loaded:
            self.load_all()
        
        by_risk = {'low': 0, 'medium': 0, 'high': 0, 'critical': 0}
        for s in self._skills.values():
            if s.risk_level in by_risk:
                by_risk[s.risk_level] += 1
        
        return {
            'total': len(self._skills),
            'enabled': len(self.get_enabled_skills()),
            'by_risk': by_risk,
            'tags': list(self._skill_index.keys()),
            'skills': [s.name for s in self._skills.values() if s.enabled],
        }


# Instância global
_loader: Optional[SkillLoader] = None

def get_skill_loader() -> SkillLoader:
    """Retorna instância global do carregador de skills."""
    global _loader
    if _loader is None:
        _loader = SkillLoader()
    return _loader

def load_skills(force: bool = False) -> Dict[str, Skill]:
    """Carrega todos os skills."""
    return get_skill_loader().load_all(force=force)

def get_skill(name: str) -> Optional[Skill]:
    """Retorna skill pelo nome."""
    return get_skill_loader().get_skill(name)

def suggest_skill(task: str) -> Optional[Skill]:
    """Sugere skill para uma tarefa."""
    return get_skill_loader().suggest_skill(task)
