import sys, os
AG = r"D:\GBOC-New\GBOC-New\GBOC-Agent"; sys.path.insert(0, AG); os.chdir(AG)
import gboc_encoding_compat, logging; logging.disable(logging.CRITICAL)
from shared_core import SharedCore
with SharedCore().get_db_connection() as c:
    cur = c.cursor(); cur.execute(sys.argv[1])
    if cur.description:
        print(" | ".join(d[0] for d in cur.description))
        for r in cur.fetchall(): print(" | ".join(str(x) for x in r))
