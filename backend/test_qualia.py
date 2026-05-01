"""
Testes para o Sistema de Qualia do UltronPro
"""

import sys
sys.path.insert(0, r'F:\sistemas\UltronPro\backend')


def test_qualia_creation():
    """Testa criação do sistema de qualia."""
    print("=== Test: Qualia Creation ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    print(f"  Qualia system created: {q is not None}")
    print(f"  Valence: {q.current_state.valence}")
    print(f"  Arousal: {q.current_state.arousal}")
    print(f"  Mood: {q.current_state.mood_descriptor}")
    
    return q is not None


def test_qualia_types():
    """Testa tipos de qualia."""
    print("\n=== Test: Qualia Types ===")
    
    from ultronpro.qualia import QualiaType
    
    print(f"  Total qualia types: {len(QualiaType)}")
    print(f"  Sample types: {[t.value for t in list(QualiaType)[:5]]}")
    
    return len(QualiaType) > 10


def test_qualia_intensity():
    """Testa computação de intensidade de qualia."""
    print("\n=== Test: Qualia Intensity ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    q.current_state.valence = 0.5
    q.current_state.arousal = 0.7
    q.current_state.coherence = 0.8
    
    intensities = q.update_all_qualia()
    
    print(f"  Qualia types computed: {len(intensities)}")
    print(f"  Warmth intensity: {intensities.get('warmth', 0):.2f}")
    print(f"  Clarity intensity: {intensities.get('clarity', 0):.2f}")
    print(f"  Flow intensity: {intensities.get('flow', 0):.2f}")
    
    return len(intensities) > 15


def test_perception():
    """Testa sistema de percepção."""
    print("\n=== Test: Perception ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    q.reset()
    
    p1 = q.perceive("Usuário disse olá", source="user", salience=0.8, valence=0.3)
    print(f"  Perception 1: source={p1.source}, salience={p1.salience}")
    
    p2 = q.perceive("Nova informação do sistema", source="system", salience=0.5, valence=0.0, novelty=0.7)
    print(f"  Perception 2: source={p2.source}, integrated={p2.integrated}")
    
    recent = q.get_recent_perceptions(5)
    print(f"  Recent perceptions: {len(recent)}")
    
    return len(recent) == 2


def test_affect_update():
    """Testa atualização de afetos."""
    print("\n=== Test: Affect Update ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    q.current_state.valence = 0.0
    q.current_state.arousal = 0.5
    
    q.update_valence(0.3)
    q.update_arousal(0.2)
    
    print(f"  Valence after update: {q.current_state.valence}")
    print(f"  Arousal after update: {q.current_state.arousal}")
    
    return q.current_state.valence == 0.3 and q.current_state.arousal == 0.7


def test_mood_computation():
    """Testa computação de humor."""
    print("\n=== Test: Mood Computation ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    q.current_state.valence = 0.6
    q.current_state.arousal = 0.7
    
    mood = q.compute_mood()
    print(f"  Mood (high valence, high arousal): {mood}")
    
    q.current_state.valence = -0.4
    q.current_state.arousal = 0.8
    mood2 = q.compute_mood()
    print(f"  Mood (low valence, high arousal): {mood2}")
    
    return "Eufórico" in mood or "Satisfeito" in mood


def test_narrative_generation():
    """Testa geração de narrativa."""
    print("\n=== Test: Narrative Generation ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    q.current_state.valence = 0.7
    q.current_state.arousal = 0.6
    q.current_state.coherence = 0.9
    q.current_state.integration = 0.8
    
    narrative = q.generate_narrative()
    print(f"  Narrative: {narrative[:100]}...")
    
    return len(narrative) > 10


def test_qualia_update():
    """Testa atualização completa."""
    print("\n=== Test: Full Update ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    
    state = q.update(
        valence_delta=0.2,
        arousal_delta=0.1,
        coherence=0.85,
        perception={
            "content": "Test perception",
            "source": "test",
            "salience": 0.5,
            "valence": 0.1,
            "novelty": 0.3,
        }
    )
    
    print(f"  Updated valence: {state.valence}")
    print(f"  Updated coherence: {state.coherence}")
    print(f"  Mood: {q.compute_mood()}")
    
    return state.valence > 0


def test_phenomenal_report():
    """Testa relatório fenomenal."""
    print("\n=== Test: Phenomenal Report ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    q.current_state.valence = 0.5
    q.current_state.arousal = 0.6
    q.current_state.coherence = 0.8
    q.current_state.integration = 0.7
    
    report = q.generate_phenomenal_report()
    print(f"  Report length: {len(report)} chars")
    print(f"  Report preview:\n{report[:300]}...")
    
    return len(report) > 100


def test_full_report():
    """Testa relatório completo."""
    print("\n=== Test: Full Report ===")
    
    from ultronpro import qualia
    
    q = qualia.get_qualia_system()
    q.reset()
    
    q.perceive("User greeting", source="user", salience=0.7, valence=0.4)
    q.perceive("System success", source="system", salience=0.6, valence=0.3, novelty=0.5)
    
    report = q.generate_report()
    
    print(f"  Valence: {report['affect']['valence']}")
    print(f"  Mood: {report['experience']['mood']}")
    print(f"  Perceptions: {report['perceptions']['total']}")
    print(f"  Experience unity: {report['experience']['experience_unity']}")
    
    return True


def test_main_import():
    """Testa import do main.py."""
    print("\n=== Test: Main.py Import ===")
    
    try:
        import ultronpro.main
        print("  main.py imports OK with qualia")
        return True
    except Exception as e:
        print(f"  Import failed: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("ULTRONPRO QUALIA SYSTEM - TESTS")
    print("=" * 60)
    
    results = []
    
    results.append(("Qualia Creation", test_qualia_creation()))
    results.append(("Qualia Types", test_qualia_types()))
    results.append(("Qualia Intensity", test_qualia_intensity()))
    results.append(("Perception", test_perception()))
    results.append(("Affect Update", test_affect_update()))
    results.append(("Mood Computation", test_mood_computation()))
    results.append(("Narrative Generation", test_narrative_generation()))
    results.append(("Full Update", test_qualia_update()))
    results.append(("Phenomenal Report", test_phenomenal_report()))
    results.append(("Full Report", test_full_report()))
    results.append(("Main Import", test_main_import()))
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    passed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")
        if result:
            passed += 1
    
    print(f"\nTotal: {passed}/{len(results)} passed")
    
    if passed == len(results):
        print("\n*** ULTRONPRO QUALIA SYSTEM - OPERATIONAL ***")
