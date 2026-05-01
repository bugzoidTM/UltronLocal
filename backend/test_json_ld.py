import json
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from ultronpro import web_browser

sample_html = """
<html>
    <head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org/",
            "@type": "Product",
            "name": "Creatina 100% Pure",
            "brand": {
                "name": "Max Titanium"
            },
            "offers": {
                "price": "89.90",
                "priceCurrency": "BRL"
            }
        }
        </script>
    </head>
    <body>Test Page</body>
</html>
"""

results = web_browser.extract_json_ld(sample_html)
print(f"Extraction Results: {json.dumps(results, indent=2)}")

if len(results) > 0 and results[0].get('name') == "Creatina 100% Pure":
    print("SUCCESS: JSON-LD extraction working!")
else:
    print("FAILED: JSON-LD extraction failed.")
