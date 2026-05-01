import os
import glob
import re
from pathlib import Path

backend_dir = str(Path(__file__).resolve().parent)

count = 0
for filepath in glob.glob(backend_dir + "/**/*.py", recursive=True):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    new_content = content
    # replace Path(__file__).resolve().parent.parent / 'data' / '...'
    new_content = re.sub(
        r"Path\(['\"]/app/data/([^'\"]*)['\"]\)", 
        r"Path(__file__).resolve().parent.parent / 'data' / '\1'", 
        new_content
    )
    
    # replace string str(Path(__file__).resolve().parent.parent / 'data' / '...')
    new_content = re.sub(
        r"['\"]/app/data/([^'\"]*)['\"]", 
        r"str(Path(__file__).resolve().parent.parent / 'data' / '\1')", 
        new_content
    )
    
    # replace string str(Path(__file__).resolve().parent.parent / 'ultronpro'...)
    new_content = re.sub(
        r"['\"]/app/ultronpro([^'\"]*)['\"]", 
        r"str(Path(__file__).resolve().parent.parent / 'ultronpro'\1)", 
        new_content
    )
    
    # replace string str(Path(__file__).resolve().parent.parent / 'ui')
    new_content = re.sub(
        r"['\"]/app/ui['\"]", 
        r"str(Path(__file__).resolve().parent.parent / 'ui')", 
        new_content
    )
    
    # replace /app/... as fallback if any
    new_content = re.sub(
        r"['\"]/app/indexes/([^'\"]*)['\"]", 
        r"str(Path(__file__).resolve().parent.parent / 'indexes' / '\1')", 
        new_content
    )
    new_content = re.sub(
        r"['\"]/app/cache/([^'\"]*)['\"]", 
        r"str(Path(__file__).resolve().parent.parent / 'cache' / '\1')", 
        new_content
    )

    # fix settings.py defaults
    if filepath.endswith("settings.py"):
        new_content = new_content.replace(
            '"http://lightrag2_lightrag2.1.ccxtpz7umbbwfjb1ew0ji8lux:9621/api"',
            '"http://127.0.0.1:9621/api"'
        )

    if new_content != content:
        if "Path(" in new_content and "import Path" not in new_content and "import pathlib" not in new_content:
            new_content = "from pathlib import Path\n" + new_content
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        count += 1
        print(f"Patched {os.path.basename(filepath)}")

# Check settings.json
settingsjson = Path(backend_dir) / 'data' / 'settings.json'
if settingsjson.exists():
    import json
    try:
        with open(settingsjson, "r", encoding="utf-8") as f:
            data = json.load(f)
        if hasattr(data, "get") and "lightrag2_" in str(data.get("lightrag_url", "")):
            data["lightrag_url"] = "http://127.0.0.1:9621/api"
            with open(settingsjson, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print("Patched settings.json URL")
    except Exception as e:
        print("Could not patch settings.json:", e)

print(f"Done patching {count} files.")
