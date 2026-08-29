#!/usr/bin/env bash
# ==============================================================================
# GBOC System v13.0.0 Enterprise Edition
# Desinstalador do GBOC Agent para Linux (Systemd & Daemons)
# ==============================================================================

set -e

if [ "$EUID" -ne 0 ]; then
  echo "[ERRO] Execute o desinstalador como root (sudo ./uninstall_agent.sh)"
  exit 1
fi

echo "==================================================================="
echo "  GBOC Agent 13.0.0 - Desinstalador para Linux"
echo "==================================================================="

read -p "Deseja realmente remover o GBOC Agent do sistema? (s/N): " CONFIRM
if [[ "$CONFIRM" != "s" && "$CONFIRM" != "S" ]]; then
  echo "Desinstalação cancelada."
  exit 0
fi

# 1. Parar e Desabilitar Serviço Systemd
if systemctl is-active --quiet gboc-agent 2>/dev/null; then
  echo "Parando serviço gboc-agent..."
  systemctl stop gboc-agent
fi

if [ -f /etc/systemd/system/gboc-agent.service ]; then
  echo "Removendo serviço systemd gboc-agent.service..."
  systemctl disable gboc-agent 2>/dev/null || true
  rm -f /etc/systemd/system/gboc-agent.service
  systemctl daemon-reload
fi

# 2. Encerrar processos remanescentes
pkill -f "agent_gboc.py" 2>/dev/null || true
pkill -f "agent_server.py" 2>/dev/null || true

# 3. Remover arquivos e diretórios
read -p "Deseja expurgar completamente o banco de dados e logs? (s/N): " PURGE
if [[ "$PURGE" == "s" || "$PURGE" == "S" ]]; then
  echo "Expurgando diretório /opt/gboc e /var/log/gboc..."
  rm -rf /opt/gboc
  rm -rf /var/log/gboc
else
  echo "Preservando diretórios de dados. Removendo binários do agente..."
  rm -rf /opt/gboc/agent_gboc.py /opt/gboc/agent_server.py
fi

echo "==================================================================="
echo "  GBOC Agent desinstalado com sucesso! ✓"
echo "==================================================================="
