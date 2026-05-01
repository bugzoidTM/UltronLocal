import re
import os

filepath = 'f:/sistemas/UltronPro/backend/ultronpro/llm.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the specific methods
content = re.sub(r'(?m)^    def _call_ollama\(.*?(?=^    def _call_ultron_infer|^\S)', '', content, flags=re.DOTALL)
content = re.sub(r'(?m)^    def _call_ultron_infer\(.*?(?=^    def _call_ollama_key|^\S)', '', content, flags=re.DOTALL)
content = re.sub(r'(?m)^    def _call_ollama_key\(.*?(?=^    def _call_keyless_free|^\S)', '', content, flags=re.DOTALL)
content = re.sub(r'(?m)^    def _call_llama_cpp\(.*?(?=^    def _ensure_llama_server|^\S)', '', content, flags=re.DOTALL)
content = re.sub(r'(?m)^    def _ensure_llama_server\(.*?(?=^router = LLMRouter|^\S)', '', content, flags=re.DOTALL)

# Remove local providers strings
content = content.replace("'ollama_local', 'ultron_infer', 'llama_cpp', 'ollama'", "")
content = content.replace("'ultron_infer', 'ollama_local', 'llama_cpp', 'ollama'", "")
content = content.replace("cand in ('ollama_local', 'ultron_infer', 'llama_cpp', 'ollama')", "False")
content = content.replace("cand in ('ollama_local', 'ollama')", "False")
content = content.replace("cand == 'llama_cpp'", "False")

# Fallback block removals inside retry
content = re.sub(r'(?m)\s*if cand == \'ultron_infer\':\s*return .*?_call_ultron_infer.*$', '', content)
content = re.sub(r'(?m)\s*if cand in \(\'ollama_local\', \'ollama\'\):\s*return .*?_call_ollama.*$', '', content)
content = re.sub(r'(?m)\s*if getattr\(cand, .*?llama_cpp.*$', '', content)
content = re.sub(r'(?m)\s*elif provider in \(\'ollama\', \'ollama_local\'\):\s*resp = self._call_ollama.*?(\n\s*elif|\n\s*else)', r'\1', content)
content = re.sub(r'(?m)\s*elif provider == \'ollama_key\':\s*resp = self._call_ollama_key.*?(\n\s*elif|\n\s*else)', r'\1', content)
content = re.sub(r'(?m)\s*elif provider == \'ultron_infer\':\s*resp = self._call_ultron_infer.*?(\n\s*elif|\n\s*else)', r'\1', content)
content = re.sub(r'(?m)\s*elif provider == \'llama_cpp\':\s*resp = self._call_llama_cpp.*?(\n\s*elif|\n\s*else)', r'\1', content)

# Remove from __init__ etc
content = content.replace("'ollama_local'", "")
content = content.replace("'llama_cpp'", "")
content = content.replace("'ollama'", "")
content = content.replace("'ultron_infer'", "")

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

# Adapter update
filepath_adapter = 'f:/sistemas/UltronPro/backend/ultronpro/llm_adapter.py'
with open(filepath_adapter, 'r', encoding='utf-8') as f:
    content = f.read()

content = re.sub(r'(?m)^class OllamaProvider.*?^\S', '', content, flags=re.DOTALL)
content = content.replace("'ollama_local'", "")
content = content.replace("'ultron_infer'", "")
content = content.replace(", ,", ",")

with open(filepath_adapter, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done.")
