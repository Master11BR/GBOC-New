import sqlite3, glob
for f in glob.glob(r"D:\GBOC-New\GBOC-New\GBOC-Agent\data\duplicati_dbs\task_*.sqlite") + [r"C:\Users\Administrador\AppData\Local\Duplicati\FPSQPXSQYY.sqlite"]:
    try:
        c = sqlite3.connect("file:" + f + "?mode=ro", uri=True)
        print(f, c.execute("select count(*), datetime(max(Timestamp),'unixepoch') from Fileset").fetchone())
    except Exception as e:
        print(f, "ERRO", e)
