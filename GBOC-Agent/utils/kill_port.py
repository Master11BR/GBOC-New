#!/usr/bin/env python3
"""
GBOC Agent 11.7c - Port Killer Utility
"""
import psutil
import sys
import time

def kill_process_on_port(port):
    """Localiza e encerra processo LISTENING na porta (quando seguro)."""
    print(f"Verificando porta {port}...")

    def _listeners_on_port():
        listeners = []
        for c in psutil.net_connections(kind='inet'):
            try:
                if c.status != psutil.CONN_LISTEN:
                    continue
                if not c.laddr or c.laddr.port != port:
                    continue
                listeners.append(c)
            except Exception:
                continue
        return listeners

    for _ in range(3):
        listeners = _listeners_on_port()
        if not listeners:
            print(f"[OK] Porta {port} esta livre.")
            return

        handled = False
        for c in listeners:
            pid = c.pid
            # PID 0/None = sistema/kernel, não tentar matar
            if not pid or pid <= 4:
                print(f"[WARN] Porta {port} em uso por processo do sistema (PID: {pid}). Ignorando kill automático.")
                continue

            try:
                proc = psutil.Process(pid)
                name = proc.name()
                print(f"[WARN] Porta {port} ocupada por: {name} (PID: {pid})")
                print("Tentando encerrar...")
                proc.kill()
                handled = True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        if handled:
            print("Aguardando liberação do sistema...")
            time.sleep(1)
        else:
            # Não há processo matável; evitar loop enganoso
            print(f"[WARN] Porta {port} não pôde ser liberada automaticamente.")
            return

    print(f"[WARN] Nao foi possivel confirmar a liberacao da porta {port} apos tentativas.")

if __name__ == "__main__":
    target_port = 9200
    if len(sys.argv) > 1:
        target_port = int(sys.argv[1])
    kill_process_on_port(target_port)
