#!/usr/bin/env python3
"""
Logstash Logging Handler
Envia logs para Logstash via TCP
"""

import logging
import socket
import json
import sys
from datetime import datetime

class LogstashHandler(logging.Handler):
    """Handler que envia logs para Logstash via TCP"""
    
    def __init__(self, host='localhost', port=5044, level=logging.INFO):
        super().__init__(level)
        self.host = host
        self.port = port
        self.sock = None
        self.connect()
    
    def connect(self):
        """Conecta ao Logstash"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
        except Exception as e:
            sys.stderr.write(f"Erro ao conectar com Logstash {self.host}:{self.port}: {e}\n")
            self.sock = None
    
    def emit(self, record):
        """Envia log para Logstash"""
        if not self.sock:
            return
        
        try:
            # Criar mensagem JSON
            log_entry = {
                '@timestamp': datetime.fromtimestamp(record.created).isoformat(),
                'level': record.levelname,
                'logger': record.name,
                'message': self.format(record),
                'host': socket.gethostname(),
                'source': 'gboc-agent'
            }
            
            # Adicionar campos extras se existirem
            if hasattr(record, 'details'):
                log_entry['details'] = str(record.details)
            
            # Enviar via TCP
            message = json.dumps(log_entry) + '\n'
            self.sock.send(message.encode('utf-8'))
            
        except Exception as e:
            sys.stderr.write(f"Erro ao enviar log para Logstash: {e}\n")
            # Tentar reconectar
            self.connect()
    
    def close(self):
        """Fecha conexão"""
        if self.sock:
            self.sock.close()
        super().close()
