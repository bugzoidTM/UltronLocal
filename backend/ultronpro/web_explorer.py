import asyncio
import json
import os
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from ultronpro import web_browser, llm, store, self_model

logger = logging.getLogger("uvicorn")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
WEB_EXPLORER_LOG_PATH = DATA_DIR / "web_explorer_log.jsonl"

class WebExplorer:
    """
    Motor de Navegação Autônoma do UltronPro.
    Procura por informações na internet para preencher lacunas de conhecimento.
    """
    def __init__(self):
        self.enabled = os.getenv('ULTRON_WEB_EXPLORER', '1') == '1'
        self.interval_sec = max(300, int(os.getenv('ULTRON_WEB_EXPLORER_INTERVAL', '900') or 900))
        self.max_links_per_tick = max(1, int(os.getenv('ULTRON_WEB_EXPLORER_MAX_LINKS_PER_TICK', '1') or 1))
        self._task: Optional[asyncio.Task] = None
        self.target_topics: List[str] = []
        self._status = {
            "current_topic": None,
            "last_urls": [],
            "kb_added": 0,
            "errors": 0,
            "is_exploring": False
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def start(self):
        if not self.enabled:
            logger.info("WebExplorer: Desabilitado nas variáveis de ambiente.")
            return
        logger.info(f"WebExplorer: Iniciando (ULTRON_WEB_EXPLORER={os.getenv('ULTRON_WEB_EXPLORER')}, interval={self.interval_sec}s, max_links={self.max_links_per_tick})")
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())
            logger.info("WebExplorer: Motor de exploração iniciado em background.")

    async def _run_loop(self):
        # Aguarda estabilização
        await asyncio.sleep(float(os.getenv('ULTRON_WEB_EXPLORER_LOOP_START_DELAY_SEC', '240')))
        while self.enabled:
            try:
                from ultronpro import runtime_guard
                if await runtime_guard.checkpoint("web_explorer_loop"):
                    continue
            except Exception:
                pass
            try:
                await self.tick()
            except Exception as e:
                logger.error(f"WebExplorer: Erro no ciclo: {e}")
                self._status["errors"] += 1
            await asyncio.sleep(self.interval_sec)

    async def tick(self):
        """Um ciclo de exploração autônoma."""
        self._status["is_exploring"] = True
        
        # 1. Decidir tópico de pesquisa
        topic = await asyncio.to_thread(self._decide_research_topic)
        if not topic:
            self._status["is_exploring"] = False
            return

        self._status["current_topic"] = topic
        self._log_event("research_start", f"Iniciando pesquisa sobre: {topic}")

        # 2. Buscar no DuckDuckGo
        search_res = await asyncio.to_thread(web_browser.search_web, topic, top_k=5)
        if not search_res.get('ok') or not search_res.get('items'):
            self._log_event("search_failed", f"Nenhum resultado para: {topic}")
            self._status["is_exploring"] = False
            return

        # 3. Navegar e extrair de links promissores
        links = search_res['items']
        for item in links[:self.max_links_per_tick]:
            url = item['url']
            title = item['title']
            self._log_event("browsing", f"Navegando em: {url} ({title})")
            
            # Navegação via Puppeteer Bridge (com fallback httpx)
            res = await web_browser.browse_url_puppeteer(url)
            if not res.get('ok'):
                self._log_event("puppeteer_fallback", f"Puppeteer falhou, usando httpx fallback...")
                # Fallback: usar fetch_url simples
                res = await asyncio.to_thread(web_browser.fetch_url, url, max_chars=15000)
                if res.get('ok'):
                    res['json_ld'] = await asyncio.to_thread(web_browser.extract_json_ld, res.get('html', '')) if res.get('html') else []
                else:
                    self._log_event("browse_error", f"Falha ao carregar {url}: {res.get('error')}")
                    continue

            # Processar dados encontrados
            json_ld = res.get('json_ld', [])
            text_content = (res.get('text', '') or res.get('content', '') or '')[:10000] # Limite para o LLM
            
            if not text_content.strip():
                self._log_event("browse_error", f"Sem conteúdo de {url}")
                continue
            
            # 4. Filtrar e extrair conhecimento útil com LLM
            knowledge = await asyncio.to_thread(self._extract_knowledge, topic, text_content, json_ld)
            if knowledge and knowledge.get('useful'):
                # Salvar na base de conhecimento (episodic memory/triples)
                await asyncio.to_thread(self._apply_knowledge, knowledge)
                self._status["kb_added"] += 1
                self._status["last_urls"].append(url)
                if len(self._status["last_urls"]) > 5:
                    self._status["last_urls"].pop(0)
                
                self._log_event("knowledge_applied", f"Novo conhecimento extraído de {url}")
            else:
                self._log_event("discarded", f"Conteúdo de {url} não relevante para {topic}")

        self._status["is_exploring"] = False

    def _decide_research_topic(self) -> Optional[str]:
        """Prioriza tópicos manuais da fila, senão pergunta ao LLM qual o melhor tópico para pesquisar agora."""
        if self.target_topics:
            return self.target_topics.pop(0)
            
        # Pega objetivos ativos e estado do self_model
        try:
            from ultronpro import intrinsic_utility
            iu = intrinsic_utility._load()
            goal = iu.get('active_emergent_goal')
            if goal:
                goal_summary = f"- {goal.get('title', '')}: {goal.get('description', '')}"
            else:
                goal_summary = "Desenvolvimento de agente autônomo e expansão de conhecimento"
        except Exception as e:
            logger.warning(f"WebExplorer: Erro ao buscar objetivos: {e}")
            goal_summary = "Desenvolvimento de agente autônomo"
        
        prompt = f"""You are the epistemic curiosity engine of UltronPro. 
Suggest a SINGLE short search query (max 40 chars, in English) for technical knowledge.
Focus on: AGI, agent architectures, RLHF, DPO, LLM optimization, reasoning benchmarks.

Return ONLY the query string, no explanation."""

        try:
            self._log_event("llm_call", "Chamando LLM para decidir tópico...")
            resp = llm.complete(prompt, strategy="cheap")
            result = resp.strip().strip('"').strip("'")
            
            # Validate result - must be a short English query
            if not result or len(result) < 3 or len(result) > 50:
                self._log_event("topic_invalid", f"Tópico inválido, usando fallback: {result}")
                result = "AGI agent architectures 2024"
            
            # Ensure it's in English (basic check)
            if not result.replace(' ', '').isalnum():
                result = "AGI agent architectures 2024"
                
            self._log_event("topic_decided", f"Tópico decidido: {result}")
            return result
        except Exception as e:
            logger.error(f"WebExplorer: Erro ao decidir tópico: {e}")
            self._log_event("topic_error", f"Erro: {str(e)[:100]}")
            return "AGI agent architectures 2024"

    def _extract_knowledge(self, topic: str, content: str, json_ld: List[dict]) -> dict:
        """Usa o LLM para extrair conceitos e fatos técnicos relevantes."""
        self._log_event("llm_extract", f"Extraindo conhecimento sobre: {topic}")
        
        prompt = f"""Analyze this web content about: "{topic}"
JSON-LD data: {json.dumps(json_ld)}
Content:
---
{content[:6000]}
---

Extract ONLY technical knowledge useful for AGI/agent development.
Ignore ads, prices, or mundane info.

Return ONLY valid JSON (no markdown), format:
{{"useful": true/false, "concepts": ["concept1", "concept2"], "summary": "1-2 sentence summary", "confidence": 0.0-1.0}}"""
        try:
            self._log_event("llm_extract", f"Extraindo conhecimento sobre: {topic}")
            resp = llm.complete(prompt, strategy="extract")
            clean_json = resp.strip()
            
            # Remove markdown code blocks
            if "```json" in clean_json:
                clean_json = clean_json.split("```json")[-1].split("```")[0].strip()
            elif "```" in clean_json:
                clean_json = clean_json.split("```")[-1].split("```")[0].strip()
            
            # Remove surrounding quotes if present
            clean_json = clean_json.strip().strip('"').strip("'")
            
            # Try to parse, if fails try to fix common issues
            try:
                result = json.loads(clean_json)
            except json.JSONDecodeError as je:
                # Try to fix truncated JSON by finding the last complete object
                self._log_event("extract_retry", f"JSON malformado, tentando corrigir...")
                # Find the last closing brace and try that
                last_brace = clean_json.rfind('}')
                if last_brace > 0:
                    try:
                        result = json.loads(clean_json[:last_brace+1])
                    except:
                        raise je  # Re-raise original error
                else:
                    raise je
            
            # Validate result structure
            if not isinstance(result.get('useful'), bool):
                result['useful'] = False
            if not isinstance(result.get('concepts'), list):
                result['concepts'] = []
            if not isinstance(result.get('confidence'), (int, float)):
                result['confidence'] = 0.5
            
            self._log_event("extract_success", f"Conceitos: {result.get('concepts', [])[:3]}")
            return result
        except Exception as e:
            logger.error(f"WebExplorer: Erro ao extrair conhecimento: {e}")
            self._log_event("extract_error", f"Erro: {str(e)[:100]}")
            return {"useful": False}

    def _apply_knowledge(self, knowledge: dict):
        """Salva a descoberta na memória do sistema."""
        summary = knowledge.get('summary', 'Descoberta técnica')
        concepts = knowledge.get('concepts', [])
        topic = self._status['current_topic'] or 'unknown'
        confidence = knowledge.get('confidence', 0.5)
        
        # 1. Adiciona evento geral
        store.db.add_event("web_discovery", f"Conhecimento técnico sobre {topic}: {summary}")
        
        # 2. Adiciona conceitos como memórias de pesquisa
        for concept in concepts:
             store.add_autobiographical_memory(
                 text=f"Conceito Web: {concept}",
                 memory_type='research',
                 importance=confidence
             )
        
        # 3. Adiciona ao grafo de conhecimento (triples)
        try:
            for concept in concepts[:3]:  # Limit to top 3 concepts
                store.db.add_triple(
                    subject=topic,
                    predicate="has_concept",
                    object_=concept,
                    confidence=confidence,
                    note=f"Web explorer discovered at {datetime.now().isoformat()}"
                )
        except Exception as e:
            logger.warning(f"WebExplorer: Erro ao adicionar tripla: {e}")
        
        # 4. Adiciona insight estruturado
        try:
            store.db.add_insight(
                kind="web_discovery",
                title=f"Web Discovery: {topic[:50]}",
                text=summary,
                priority=3,
                source_id=f"web_explorer"
            )
        except Exception as e:
            logger.warning(f"WebExplorer: Erro ao adicionar insight: {e}")
        
        self._log_event("knowledge_integrated", f"Conceitos salvos: {concepts[:3]}")

    def _log_event(self, kind: str, text: str):
        """Escreve log para o frontend."""
        entry = {
            "ts": datetime.now().isoformat(),
            "kind": kind,
            "text": text,
            "topic": self._status["current_topic"]
        }
        try:
            with open(WEB_EXPLORER_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Erro ao escrever log web_explorer: {e}")

    def get_status(self) -> dict:
        return self._status

# Singleton
_explorer = WebExplorer()

def get_web_explorer() -> WebExplorer:
    return _explorer

def start_web_explorer():
    _explorer.start()
    
    # Auto-start Puppeteer Bridge se não estiver rodando (fallback no Windows)
    import subprocess
    import os
    bridge_dir = Path(__file__).resolve().parent.parent / "bin" / "puppeteer_bridge"
    if bridge_dir.exists() and (bridge_dir / "server.js").exists():
        try:
            import httpx
            # Tentar ver se já está de pé
            httpx.get("http://127.0.0.1:9010/health", timeout=1.0)
            logger.info("WebExplorer: Puppeteer Bridge já está rodando em :9010")
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException):
            logger.info("WebExplorer: Iniciando Puppeteer Bridge local...")
            try:
                subprocess.Popen(
                    ["node", "server.js"],
                    cwd=str(bridge_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ, "PUPPETEER_BRIDGE_PORT": "9010"}
                )
            except Exception as e:
                logger.error(f"WebExplorer: Falha ao iniciar bridge NPM: {e}")
