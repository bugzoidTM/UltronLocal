import json, urllib.request, time
t0 = time.time()
req = urllib.request.Request('http://127.0.0.1:8000/api/chat', data=json.dumps({'message':'oi'}).encode('utf-8'), headers={'Content-Type':'application/json'})
res = urllib.request.urlopen(req, timeout=12)
print(f'OK ({time.time()-t0:.2f}s): {res.read().decode()}')
