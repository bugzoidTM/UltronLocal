import sys
sys.path.insert(0, '.')

path = 'ultronpro/main.py'
content = open(path, 'r', encoding='utf-8').read()

# Patch meta_observer_loop
old_meta = '''            snap = _meta_observer_snapshot(limit=100)
            _workspace_publish('meta_observer', 'meta.observer', snap, salience=0.73, ttl_sec=1800)'''
new_meta = '''            snap = _meta_observer_snapshot(limit=100)
            _workspace_publish('meta_observer', 'meta.observer', snap, salience=0.73, ttl_sec=1800)
            
            # Consume top focus items to increase consumer_factor and reduce fragmentation
            try:
                for it in snap.get('focus') or []:
                    if it.get('id'):
                        store.db.mark_workspace_consumed(it['id'], 'meta_observer')
            except Exception as e:
                logger.error(f"Failed to consume items in meta_observer: {e}")'''

if old_meta in content:
    content = content.replace(old_meta, new_meta, 1)
    print("Patched meta_observer_loop")

# Patch integration_proxy_loop
old_integ = '''            snap = _integration_proxy_snapshot(limit=120)
            score = float(snap.get('integration_proxy_score') or 0.0)
            salience = 0.62 + min(0.20, (1.0 - score) * 0.20)
            _workspace_publish('integration_proxy', 'integration.proxy', snap, salience=salience, ttl_sec=3600)'''
new_integ = '''            snap = _integration_proxy_snapshot(limit=120)
            score = float(snap.get('integration_proxy_score') or 0.0)
            salience = 0.62 + min(0.20, (1.0 - score) * 0.20)
            _workspace_publish('integration_proxy', 'integration.proxy', snap, salience=salience, ttl_sec=3600)
            
            # Consume items
            try:
                items = _workspace_recent(limit=15)
                for it in items:
                    if it.get('id'):
                        store.db.mark_workspace_consumed(it['id'], 'integration_proxy')
            except Exception as e:
                pass'''

if old_integ in content:
    content = content.replace(old_integ, new_integ, 1)
    print("Patched integration_proxy_loop")

open(path, 'w', encoding='utf-8').write(content)
print("Done")
