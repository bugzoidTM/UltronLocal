import ast

filepath = r'f:\sistemas\UltronPro\backend\ultronpro\llm.py'
with open(filepath, 'r', encoding='utf-8') as f:
    source = f.read()

tree = ast.parse(source)

lines_to_remove = set()

class MethodVisitor(ast.NodeVisitor):
    def visit_FunctionDef(self, node):
        if node.name in ('_call_ollama', '_call_ultron_infer', '_call_llama_cpp', '_call_ollama_key', '_ensure_llama_server'):
            for i in range(node.lineno - 1, node.end_lineno):
                lines_to_remove.add(i)
        self.generic_visit(node)

MethodVisitor().visit(tree)

source_lines = source.splitlines()
new_lines = [line for i, line in enumerate(source_lines) if i not in lines_to_remove]

# Replace specific tuples and dict keys that were causing syntax errors before without breaking them.
new_source = "\n".join(new_lines) + "\n"

# Only safe string replacements targeting exactly the tokens inside lists/tuples without leaving syntax broken
new_source = new_source.replace("'ollama_local', 'ultron_infer', 'llama_cpp', 'ollama'", "")
new_source = new_source.replace("'ultron_infer', 'ollama_local', 'llama_cpp', 'ollama'", "")
new_source = new_source.replace("'ollama', 'ollama_local'", "")
new_source = new_source.replace("'ollama_local', 'ultron_infer'", "")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_source)

print('Métodos AST removidos.')
