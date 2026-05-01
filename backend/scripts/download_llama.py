import os
import urllib.request
import zipfile
import sys

# Correct URL for CPU x64 (AVX2 is included in this one usually)
url = 'https://github.com/ggml-org/llama.cpp/releases/download/b8470/llama-b8470-bin-win-cpu-x64.zip'
dest_dir = r'f:\sistemas\UltronPro\backend\bin\llama_cpp'
zip_path = r'f:\sistemas\UltronPro\backend\bin\llama.zip'

if not os.path.exists(os.path.dirname(zip_path)):
    os.makedirs(os.path.dirname(zip_path))

try:
    print(f"Downloading {url}...")
    opener = urllib.request.build_opener()
    opener.addheaders = [('User-agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)
    
    urllib.request.urlretrieve(url, zip_path)
    print("Download complete.")
    
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
        
    print(f"Extracting to {dest_dir}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(dest_dir)
    print("Extraction complete.")
    
    os.remove(zip_path)
    print("Cleanup complete.")
    
    print("Contents of dest_dir:")
    for f in os.listdir(dest_dir):
        print(f" - {f}")

except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
