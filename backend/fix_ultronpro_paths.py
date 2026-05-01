import glob
import re
from pathlib import Path

base_dir = Path(__file__).resolve().parent / 'ultronpro'
for fpath in glob.glob(str(base_dir) + r'\**\*.py', recursive=True):
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for the badly formatted string: 'ultronpro'/something)
    # Replaces 'ultronpro'/data_language_eval.json) with 'ultronpro/data_language_eval.json')
    new_content = re.sub(r"'ultronpro'/([^)]+)\)", r"'ultronpro/\1')", content)
    
    if new_content != content:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print('Fixed:', fpath)
