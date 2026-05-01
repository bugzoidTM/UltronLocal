import asyncio
import os
import json
import logging
import sys

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ultronpro.local_reasoning import LocalAutonomousLoop
from ultronpro import llm

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_local")

async def test_planner():
    logger.info("--- Testing LocalPlanner (Triage) ---")
    
    # 1. Simple query (should be SOLVE_LOCAL)
    q1 = "Quem é você?"
    p1 = await LocalAutonomousLoop.plan(q1)
    logger.info(f"Query 1: {q1} -> Decision: {p1.get('decision')} ({p1.get('reason')})")
    
    # 2. Complex query (should be CALL_BACKBONE)
    q2 = "Analise o impacto da inteligência artificial na economia global e crie um ensaio de 5 parágrafos."
    p2 = await LocalAutonomousLoop.plan(q2)
    logger.info(f"Query 2: {q2} -> Decision: {p2.get('decision')} ({p2.get('reason')})")

async def test_evaluator():
    logger.info("\n--- Testing LocalEvaluator (Result Validation) ---")
    
    obj = "Descreva as metas atuais."
    res_good = "As metas atuais focam na Fase 7.3 do Roadmap, focando em raciocínio local."
    res_bad = "Eu sou um modelo de linguagem treinado por ..."
    
    e1 = await LocalAutonomousLoop.evaluate(obj, res_good)
    logger.info(f"Good Result Evaluation: {e1.get('status')} ({e1.get('feedback')})")
    
    e2 = await LocalAutonomousLoop.evaluate(obj, res_bad)
    logger.info(f"Bad Result Evaluation: {e2.get('status')} ({e2.get('feedback')})")

async def main():
    try:
        await test_planner()
        await test_evaluator()
    except Exception as e:
        logger.error(f"Verification failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
