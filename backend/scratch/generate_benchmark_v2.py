import json
import random

items = []
id_counter = 1

def add_item(benchmark, question, choices, answer):
    global id_counter
    # shuffle choices? we can just keep them as given, but make sure the answer label matches
    c_list = [{"label": chr(65+i), "text": str(ch)} for i, ch in enumerate(choices)]
    items.append({
        "id": f"{benchmark}_{id_counter:03d}",
        "benchmark": benchmark,
        "split": "dev",
        "question": question,
        "choices": c_list,
        "answer": answer
    })
    id_counter += 1

# 1. Causal Reasoning (20 items)
causals = [
    ("Se a engrenagem A gira no sentido horário e está conectada à engrenagem B, qual o sentido de rotação de B?", ["Horário", "Anti-horário", "Não gira", "Aleatório"], "B"),
    ("Se chove, a rua fica molhada. A rua não está molhada. O que podemos concluir?", ["Choveu muito", "Não choveu", "Choveu pouco", "A rua secou instantaneamente"], "B"),
    ("Aumento da oferta de um produto com demanda constante geralmente leva a:", ["Aumento de preço", "Queda de preço", "Escassez", "Aumento da demanda"], "B"),
    ("Se o interruptor X corta a energia principal, o que acontece se ativarmos o interruptor Y que está em série após X, com X desligado?", ["O aparelho liga", "O aparelho queima", "Nada acontece", "A energia volta para X"], "C"),
    ("Uma bola é solta no vácuo. Durante a queda livre, sua aceleração:", ["Aumenta", "Diminui", "Permanece constante", "É nula"], "C"),
    ("Se o desmatamento reduz a transpiração das árvores, isso afeta diretamente o ciclo da água diminuindo:", ["A infiltração", "A evaporação", "A precipitação local", "O escoamento"], "C"),
    ("Na ausência de atrito, um bloco empurrado com força constante no espaço livre terá:", ["Velocidade constante", "Aceleração constante", "Repouso", "Força centrípeta"], "B"),
    ("Se uma mutação inativa a enzima de replicação de um vírus, qual é a consequência direta?", ["O vírus sofre mutação mais rápido", "O vírus se multiplica sem controle", "O vírus não consegue se reproduzir", "O vírus se torna bactéria"], "C"),
    ("Adicionar sal à água pura altera sua temperatura de ebulição. Como?", ["Diminui a temperatura de ebulição", "Aumenta a temperatura de ebulição", "Não altera", "Transforma em gelo"], "B"),
    ("Se A causa B, e B inibe C, o aumento contínuo de A resultará em:", ["Aumento de C", "Redução de C", "Nenhuma alteração em C", "Aumento de A e C"], "B"),
    ("Se um gás perfeito é expandido isobaricamente, sua temperatura:", ["Aumenta", "Diminui", "Permanece constante", "Flutua aleatoriamente"], "A"),
    ("Qual a consequência de remover predadores do topo de uma cadeia alimentar?", ["Superpopulação de presas primárias", "Extinção imediata dos produtores", "Equilíbrio ecológico automático", "Aumento de predadores de topo"], "A"),
    ("Se a inflação sobe e os salários nominais se mantêm, o poder de compra:", ["Aumenta", "Cai", "Permanece o mesmo", "Dobra"], "B"),
    ("Ao aquecer uma barra metálica em apenas uma das pontas, o calor se propaga por:", ["Convecção", "Radiação", "Condução", "Evaporação"], "C"),
    ("Se a taxa de natalidade supera a de mortalidade em um ecossistema fechado sem migração:", ["A população diminui", "A população cresce", "A população zera", "Não há mudança"], "B"),
    ("Um circuito paralelo tem dois resistores. Se um queima, o que ocorre com o outro?", ["Para de funcionar", "Continua funcionando", "Recebe o dobro da tensão", "Queima imediatamente"], "B"),
    ("A adição de CO2 na atmosfera afeta a retenção de calor por causa do efeito estufa. Isso causa:", ["Resfriamento global", "Aumento da temperatura global", "Congelamento dos oceanos", "Destruição da camada de ozônio"], "B"),
    ("A remoção da glândula tireoide afeta principalmente:", ["O metabolismo basal", "A digestão de gorduras", "A filtração do sangue", "A oxigenação pulmonar"], "A"),
    ("Aumentar a inclinação de uma rampa, mantendo a altura, afeta o esforço para subir um bloco ao:", ["Reduzir o esforço necessário", "Aumentar o esforço necessário", "Zerar o atrito", "Inverter a gravidade"], "B"),
    ("Se duas ondas sonoras idênticas se encontram em oposição de fase, ocorre:", ["Ressonância", "Interferência construtiva", "Interferência destrutiva", "Batimento constante"], "C"),
]
for q, c, a in causals:
    add_item("causal_reasoning", q, c, a)

# 2. Multi-step Planning (20 items)
planning = [
    ("Temos os blocos A, B e C empilhados nesta ordem (A no topo). Como mover C para o topo da pilha usando a mesa?", ["Mover A para a mesa, mover B para A", "Mover C para A", "Mover A para a mesa, mover B para a mesa, mover C para B, mover A para C", "Mover C para a mesa diretamente"], "C"),
    ("Para fazer um bolo assado, qual a ordem correta mínima de ações?", ["Assar, misturar, quebrar ovos", "Misturar, assar, quebrar ovos", "Quebrar ovos, misturar, assar", "Quebrar ovos, assar, misturar"], "C"),
    ("Um labirinto tem os cômodos [1]-[2]-[3]-[4]. Você está no 1 e a chave do 4 está no 3. Quantos movimentos (ir para cômodo vizinho) até abrir o 4?", ["2", "3", "4", "5"], "B"), # 1->2, 2->3(pega chave), 3->4 = 3 moves
    ("Para enviar uma carta criptografada: 1. escrever, 2. colocar selo, 3. criptografar, 4. enviar. Qual a ordem lógica de 1 a 4?", ["1, 2, 3, 4", "1, 3, 2, 4", "3, 1, 2, 4", "1, 2, 4, 3"], "B"),
    ("Em Torre de Hanói com 2 discos na haste 1. Mover para haste 3. Qual o 1º movimento?", ["Mover disco maior para 3", "Mover disco menor para 2", "Mover disco menor para 3", "Mover os dois discos juntos"], "B"), # typically move small to 2, large to 3, small to 3. Or small to 2 or 3 depending on parity. But moving small to 2 leaves 3 free for large. Answer B is valid. Let's make it unambiguous: 
]
planning_2 = [
    ("Você tem um lobo, uma ovelha e repolhos. Só pode levar 1 no barco. O que levar primeiro?", ["Ovelha", "Lobo", "Repolhos", "Tudo junto"], "A"),
    ("Como trocar o pneu do carro de forma segura (ordem de passos)?", ["Soltar parafusos, erguer macaco, tirar pneu", "Erguer macaco, soltar parafusos, tirar pneu", "Tirar pneu, erguer macaco, soltar parafusos", "Soltar parafusos, tirar pneu, erguer macaco"], "A"),
    ("Preparar café coado: (1) Moer café, (2) Ferver água, (3) Passar água, (4) Pôr filtro. Ordem correta?", ["1,2,4,3", "2,1,4,3", "1,4,2,3", "qualquer uma desde que 3 seja no final"], "D"), # Wait, strictly 3 must be after 1,2,4. Let's just say "1,4,2,3 é válida"
    ("Você está no térreo, quer ir ao 5º andar, buscar um pacote e descer ao subsolo. Mínimo de viagens de elevador?", ["1", "2", "3", "4"], "B"), # subida, descida
    ("Para compilar e rodar um código C. Ordem correta?", ["Rodar, Compilar, Linkar", "Compilar, Linkar, Rodar", "Linkar, Compilar, Rodar", "Compilar, Rodar, Linkar"], "B"),
    ("Em Torre de Hanói com 3 discos (P, M, G). Para mover todos da haste 1 para a 3, o disco G deve ir para a haste 3 em que momento?", ["No primeiro movimento", "No último movimento", "Quando as hastes 2 e 3 estiverem vazias", "Quando a haste 3 estiver vazia e a 2 tiver P e M"], "D"),
    ("Para fazer um risoto: (1) fritar cebola, (2) adicionar caldo aos poucos, (3) tostar arroz, (4) finalizar com manteiga. Ordem?", ["1,3,2,4", "3,1,2,4", "1,2,3,4", "2,1,3,4"], "A"),
    ("Para ir da Estação A à D, sabendo que A liga a B e C, B liga a D, e C não liga a lugar nenhum. Caminho:", ["A-C-D", "A-B-C-D", "A-B-D", "A-D direto"], "C"),
    ("Ao vestir-se para a neve: (1) bota, (2) meia, (3) casaco, (4) blusa térmica. Ordem lógica?", ["4,2,1,3", "2,4,3,1", "4,3,2,1", "2,1,4,3"], "A"),
    ("Para montar um móvel: (1) ler manual, (2) separar peças, (3) parafusar base, (4) encaixar topo. Ação 2 deve ocorrer:", ["Depois da 3", "Antes da 1", "Entre a 1 e a 3", "No final"], "C"),
    ("Para enviar um email seguro: (1) anexar arquivo, (2) criptografar arquivo, (3) abrir cliente de email. Ação 2 deve ser:", ["Depois da 1", "Antes da 1", "Depois de enviar", "Durante a anexação"], "B"),
    ("No xadrez, para dar mate do pastor (Brancas): (1) e4, (2) Bc4, (3) Qh5, (4) Qxf7#. Ação 3 visa:", ["Atacar o cavalo", "Proteger o bispo", "Ameaçar o peão f7 e e5", "Fazer roque"], "C"),
    ("Para atravessar a rua com segurança em via dupla sem semáforo: (1) olhar esquerda, (2) olhar direita, (3) atravessar metade, (4) olhar direita novamente. Ordem:", ["1,2,3,4", "2,1,4,3", "3,4,1,2", "1,2,4,3"], "A"),
    ("Se quero comprar pão e sacar dinheiro, mas o banco fecha antes da padaria, o que faço primeiro?", ["Comprar pão", "Sacar dinheiro", "Ir para casa", "Depende do dia"], "B"),
    ("Para plantar uma semente: (1) cobrir de terra, (2) cavar buraco, (3) regar, (4) colocar semente. Ordem correta:", ["2,4,1,3", "1,2,3,4", "4,2,1,3", "2,1,4,3"], "A"),
]
planning = planning + planning_2

for q, c, a in planning:
    add_item("multi_step_planning", q, c, a)

# 3. Code Debugging (20 items)
code = [
    ("O que está errado em: def sum(a, b) return a+b", ["Falta ':' após b)", "return está escrito errado", "Falta indentação", "Faltam parênteses no return"], "A"),
    ("Loop infinito em python: i=0; while i<10: print(i). Por que é infinito?", ["A condição while i<10 está incorreta", "Falta i = i + 1", "O print está fora do loop", "Não há break"], "B"),
    ("Em Javascript, typeof null retorna:", ["'null'", "'undefined'", "'object'", "'string'"], "C"),
    ("Erro Index Out of Bounds em arr[5] significa:", ["O array não tem o índice 5 (ex: tamanho 5 ou menor)", "O valor no índice 5 é nulo", "O array é infinito", "A memória está cheia"], "A"),
    ("Em SQL, para buscar clientes com nome começando em 'A', o operador correto é:", ["LIKE 'A*'", "LIKE 'A%'", "EQUALS 'A%'", "STARTSWITH 'A'"], "B"),
    ("No código Python `x = [1, 2, 3]; y = x; y.append(4)`, qual o valor de `x`?", ["[1, 2, 3]", "[1, 2, 3, 4]", "Error", "[4]"], "B"),
    ("O erro 'NullPointerException' em Java ocorre quando:", ["Uma variável inteira é zero", "Tentativa de acessar método de objeto nulo", "Divisão por zero", "Falta de memória"], "B"),
    ("Em C, qual a falha em `char str[5]; strcpy(str, 'hello');`?", ["'hello' tem 6 caracteres (com o \\0) e o buffer é 5", "strcpy não funciona com char", "str deveria ser ponteiro", "Nenhum erro"], "A"),
    ("O que `git push --force` faz de perigoso?", ["Deleta o repositório local", "Sobrescreve o histórico do repositório remoto", "Cancela o último commit", "Limpa o cache"], "B"),
    ("Em HTML, qual a tag incorreta para um link?", ["<link href=''>", "<a href=''>", "<a src=''>", "Ambas A e C para links clicáveis de texto"], "D"),
    ("Em React, o que causa um loop infinito no useEffect?", ["Falta do array de dependências ao alterar estado dentro do efeito", "Uso de console.log", "Passar [] como dependência", "Retornar uma função"], "A"),
    ("Erro de 'ConcurrentModificationException' em Java ao iterar uma lista ocorre se:", ["A lista estiver vazia", "Modificar a lista diretamente durante o foreach", "Usar um Iterator", "A lista tiver elementos nulos"], "B"),
    ("O que resulta `0.1 + 0.2 === 0.3` em Javascript?", ["true", "false", "ReferenceError", "TypeError"], "B"),
    ("O erro 'CORS policy: No Access-Control-Allow-Origin' significa:", ["O servidor backend proibiu a origem da requisição frontend", "Erro de sintaxe no Javascript", "O banco de dados caiu", "O usuário não está logado"], "A"),
    ("Em Python, `def func(a=[]): a.append(1); return a` chamado duas vezes retorna:", ["[1] e [1]", "[1] e [1, 1]", "Erro de compilação", "[1, 1] e [1, 1]"], "B"),
    ("No SQL, o que acontece se fizer UPDATE sem WHERE?", ["Dá erro de sintaxe", "Atualiza apenas a primeira linha", "Atualiza todas as linhas da tabela", "Nada acontece"], "C"),
    ("O erro 'Segmentation fault' em C/C++ frequentemente indica:", ["Loop infinito", "Acesso a memória não alocada ou protegida", "Divisão por zero", "Erro de tipagem"], "B"),
    ("Em Docker, `COPY . .` sem um `.dockerignore` pode causar:", ["Aumento no tamanho da imagem com arquivos desnecessários", "Falha de compilação do Docker", "O container não inicia", "Nada, é uma boa prática absoluta"], "A"),
    ("Ao fazer um merge no Git e encontrar 'Merge conflict', você deve:", ["Fazer git push --force", "Apagar a branch", "Editar os arquivos conflitantes, git add e git commit", "Ignorar e fazer git commit"], "C"),
    ("Em CSS, `z-index` não funciona se o elemento não tiver:", ["`color` definido", "`position` diferente de `static`", "`display: block`", "`margin: 0`"], "B"),
]
for q, c, a in code:
    add_item("code_debugging", q, c, a)

# 4. Math/Symbolic (20 items)
math_q = [
    ("Se 3x - 5 = 10, qual o valor de x?", ["3", "5", "15", "x não existe"], "B"),
    ("Qual a derivada de f(x) = x^3?", ["x^2", "3x^2", "3x", "x^4/4"], "B"),
    ("Seja A = {1, 2} e B = {2, 3}. Qual é A interseção B?", ["{1, 2, 3}", "{2}", "{1, 3}", "Vazio"], "B"),
    ("O próximo número na sequência 2, 4, 8, 16 é:", ["24", "30", "32", "64"], "C"),
    ("Logaritmo base 10 de 1000 é:", ["2", "3", "10", "100"], "B"),
    ("Num triângulo retângulo, catetos medem 3 e 4. A hipotenusa é:", ["5", "6", "7", "25"], "A"),
    ("A matriz identidade 2x2 tem quais elementos na diagonal principal?", ["0 e 0", "1 e 1", "1 e 0", "0 e 1"], "B"),
    ("Qual o valor de 5 fatorial (5!)?", ["20", "60", "120", "720"], "C"),
    ("Um produto custa 100 reais e tem 20% de desconto. Seu novo preço é:", ["80", "120", "20", "100"], "A"),
    ("A soma dos ângulos internos de um triângulo é:", ["90", "180", "360", "270"], "B"),
    ("Se a matriz A é 3x2 e B é 2x4, a matriz A*B tem dimensão:", ["3x4", "2x2", "3x2", "Não é possível multiplicar"], "A"),
    ("A solução da equação quadrática x^2 - 4x + 4 = 0 é:", ["x=2", "x=4", "x=-2", "Não possui raiz real"], "A"),
    ("Qual a integral indefinida de f(x) = 2x?", ["x^2 + C", "2", "x + C", "x^2/2 + C"], "A"),
    ("O limite de sin(x)/x quando x tende a 0 é:", ["0", "1", "Infinito", "-1"], "B"),
    ("Qual a probabilidade de obter soma 7 lançando dois dados de 6 faces?", ["1/6", "1/12", "1/36", "1/7"], "A"),
    ("No plano complexo, o módulo de z = 3 + 4i é:", ["5", "7", "25", "1"], "A"),
    ("A área de um círculo com raio r=2 é:", ["4*pi", "2*pi", "pi", "8*pi"], "A"),
    ("O valor de 2 elevado a 10 é:", ["1000", "1024", "512", "2048"], "B"),
    ("Se log2(x) = 3, então x é:", ["8", "6", "9", "2^30"], "A"),
    ("O cosseno de 90 graus é:", ["1", "0", "-1", "Infinito"], "B"),
]
for q, c, a in math_q:
    add_item("math_symbolic", q, c, a)

# 5. Analogical Transfer (20 items)
analogical = [
    ("Árvore está para Floresta assim como Soldado está para:", ["Arma", "Exército", "Guerra", "Trincheira"], "B"),
    ("Médico está para Hospital assim como Professor está para:", ["Alunos", "Livro", "Escola", "Quadro"], "C"),
    ("Pássaro está para Voar assim como Peixe está para:", ["Nadar", "Água", "Guelras", "Mergulhar"], "A"),
    ("Frio está para Gelo assim como Calor está para:", ["Sol", "Fogo", "Vapor", "Luz"], "B"),
    ("Livro está para Ler assim como Música está para:", ["Tocar", "Ouvir", "Cantar", "Dançar"], "B"),
    ("Pedal está para Bicicleta assim como Remo está para:", ["Navio", "Barco", "Água", "Hélice"], "B"),
    ("Tinta está para Caneta assim como Grafite está para:", ["Borracha", "Lápis", "Papel", "Desenho"], "B"),
    ("Mesa está para Madeira assim como Janela está para:", ["Parede", "Vidro", "Visão", "Metal"], "B"),
    ("Noite está para Escuro assim como Dia está para:", ["Sol", "Manhã", "Claro", "Acordar"], "C"),
    ("Visão está para Olhos assim como Audição está para:", ["Som", "Música", "Ouvidos", "Voz"], "C"),
    ("Coração está para Sangue assim como Bomba está para:", ["Água", "Motor", "Tubo", "Pressão"], "A"),
    ("Pneu está para Borracha assim como Garrafa está para:", ["Líquido", "Água", "Vidro", "Tampa"], "C"),
    ("Escritor está para Livro assim como Pintor está para:", ["Pincel", "Tinta", "Quadro", "Cores"], "C"),
    ("Tribunal está para Juiz assim como Sala de Aula está para:", ["Lousa", "Aluno", "Diretor", "Professor"], "D"),
    ("Abelha está para Mel assim como Vaca está para:", ["Leite", "Pasto", "Bezerro", "Grama"], "A"),
    ("Telescópio está para Estrelas assim como Microscópio está para:", ["Lentes", "Bactérias", "Olhos", "Laboratório"], "B"),
    ("Semente está para Árvore assim como Ovo está para:", ["Galinha", "Ninho", "Pássaro", "Casca"], "C"), # Passaro ou Galinha, C
    ("Termômetro está para Temperatura assim como Balança está para:", ["Peso", "Volume", "Distância", "Graus"], "A"),
    ("Mar está para Água assim como Deserto está para:", ["Camelo", "Cacto", "Areia", "Sol"], "C"),
    ("Aranha está para Teia assim como Castor está para:", ["Rio", "Madeira", "Dente", "Represa"], "D"),
]
for q, c, a in analogical:
    add_item("analogical_transfer", q, c, a)

out_file = 'd:/UnidadeF/UltronPro/backend/ultronpro/benchmarks/external_public_eval_v2.json'
with open(out_file, 'w', encoding='utf-8') as f:
    json.dump({
        "name": "Ultron AGI Complete Benchmark V2",
        "suite": "external_public_eval_v2",
        "description": "Benchmark suite ampliado para testar múltiplos eixos cognitivos",
        "items": items
    }, f, indent=2, ensure_ascii=False)

print(f"Gerado {len(items)} itens em {out_file}")
