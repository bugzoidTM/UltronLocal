import re

path = r'f:\sistemas\UltronPro\backend\ultronpro\main.py'
with open(path, 'rb') as f:
    raw = f.read()

# Find and remove the CausalTripleIngestRequest class (CRLF file)
idx = raw.find(b'class CausalTripleIngestRequest(BaseModel):')
if idx == -1:
    print('Not found')
else:
    # Find next @app decorator after the class
    end_idx = raw.find(b'\r\n@app.', idx)
    if end_idx == -1:
        end_idx = raw.find(b'\r\nasync def ', idx)
    print(f'Found at byte {idx}, class ends at {end_idx}')
    print(repr(raw[idx:end_idx+2]))
    new_raw = raw[:idx] + raw[end_idx+2:]
    with open(path, 'wb') as f:
        f.write(new_raw)
    print('Saved.')
