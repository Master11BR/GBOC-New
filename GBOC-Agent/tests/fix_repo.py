import psycopg2, json

conn = psycopg2.connect(host='localhost', port=5432, dbname='gboc_agent', user='postgres', password='Stoms2025+')
cur = conn.cursor()

cur.execute('SELECT config FROM repositories WHERE id=8')
row = cur.fetchone()
cfg = json.loads(row[0]) if isinstance(row[0], str) else row[0]

cfg['prefix'] = 'duplicati-prod'
new_cfg = json.dumps(cfg)

cur.execute('UPDATE repositories SET config=%s WHERE id=8', (new_cfg,))
conn.commit()

print(f"Updated prefix to: {cfg['prefix']}")

# Verify
cur.execute('SELECT config FROM repositories WHERE id=8')
row2 = cur.fetchone()
cfg2 = json.loads(row2[0]) if isinstance(row2[0], str) else row2[0]
print(f"Verified prefix: {cfg2['prefix']}")

conn.close()
