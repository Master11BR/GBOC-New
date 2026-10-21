# Dois processos com o Scheduler real avaliando a mesma tarefa no mesmo minuto: só um pode disparar.
import os, sys, contextlib, multiprocessing as mp
from datetime import datetime
AGENT = r"D:\GBOC-New\GBOC-New\GBOC-Agent"
sys.path.insert(0, AGENT); os.chdir(AGENT)
import psycopg2
cfg = dict(dbname="gboc_oldschema_test", host="localhost", port=5432, user="postgres",
           password=os.getenv("POSTGRES_PASSWORD", "Stoms2025+"))

class TM:
    def __init__(self, q): self.q = q
    def trigger_task(self, tid): self.q.put((os.getpid(), tid)); return {"status": "success", "execution_id": 0}
class Core:
    def __init__(self, q): self.task_manager = TM(q)
    @contextlib.contextmanager
    def get_db_connection(self):
        k = psycopg2.connect(**cfg)
        try: yield k
        finally: k.close()

def worker(q, barrier, now):
    import logging; logging.basicConfig(level=logging.INFO, format="%(process)d %(message)s")
    import shared_core
    fake = Core(q)
    shared_core.get_shared_core = lambda: fake    # operation_settings usa o core: nunca o banco real no teste
    from engines.scheduler import Scheduler
    s = Scheduler(fake); barrier.wait(); s._check_scheduled_tasks(now)

if __name__ == "__main__":
    k = psycopg2.connect(**cfg); c = k.cursor()
    c.execute("DROP TABLE IF EXISTS scheduler_fires")
    c.execute("UPDATE tasks SET enabled=TRUE, schedule_enabled=TRUE, status='idle', schedule_cron='* * * * *' WHERE id=2"); k.commit(); k.close()
    q = mp.Queue(); b = mp.Barrier(6); now = datetime.now().replace(second=0, microsecond=0)
    ps = [mp.Process(target=worker, args=(q, b, now)) for _ in range(6)]
    [p.start() for p in ps]; [p.join() for p in ps]
    fired = []
    while not q.empty(): fired.append(q.get())
    print("6 processos, mesmo minuto -> disparos:", fired)
    fired2 = []
    p = mp.Process(target=worker, args=(q, mp.Barrier(1), now.replace(minute=(now.minute + 1) % 60))); p.start(); p.join()
    while not q.empty(): fired2.append(q.get())
    print("minuto seguinte -> disparos:", fired2)
