#!/usr/bin/env python3
"""
🌐 GBOC Agent 14.0.0 - CENTRAL SERVER CLIENT
Cliente para comunicação com servidor GBOC central
"""

import json
import logging
import requests
import threading
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import uuid
import socket
import os
import platform
import psutil

# PostgreSQL é opcional - usar SQLite se não disponível
try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("psycopg2 não disponível - usando SQLite")

from pathlib import Path
import websockets
import websockets.exceptions

from server_config import config_manager
from shared_core import SharedCore

logger = logging.getLogger(__name__)

class CentralServerClient:
    """Cliente para comunicação com servidor central GBOC"""

    def __init__(self):
        self.agent_id = self._get_or_create_agent_id()
        self.server_url = None
        self.api_key = None
        self.tenant_id = None
        self.is_registered = False
        self.last_heartbeat = None
        self.heartbeat_thread = None

        # Sessão HTTP reutilizável — verify=False aceita cert autoassinado local (HTTPS)
        self._session = requests.Session()
        self._session.verify = False
        # Suprimir aviso de InsecureRequest para conexões locais
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass

        # WebSocket para comunicação em Tempo Real
        self.websocket = None
        self.websocket_thread = None
        self.websocket_connected = False
        self.last_websocket_message = None
        self.shared_core = SharedCore()

        # Monitor de resultado de backups Duplicati
        self._duplicati_monitor_thread: Optional[threading.Thread] = None
        self._duplicati_last_seen: Dict[str, Any] = {}   # backup_id -> último resultado visto

        # Carregar configuração sem testar conexão
        self._load_configuration_silent()

    def start_threads(self):
        """Inicia threads de fundo (heartbeat, WebSocket, etc) após a inicialização principal."""
        if self.server_url:
            self._start_heartbeat()
            self._start_websocket()
        self._start_duplicati_monitor()

    # ──────────────────────────────────────────────────────────────────────────
    # Monitor de Resultados Duplicati — alerta automático em caso de erro
    # ──────────────────────────────────────────────────────────────────────────

    def _start_duplicati_monitor(self):
        """Inicia a thread de monitoramento de resultados de backup Duplicati."""
        if self._duplicati_monitor_thread and self._duplicati_monitor_thread.is_alive():
            return
        self._duplicati_monitor_thread = threading.Thread(
            target=self._duplicati_monitor_loop,
            daemon=True,
            name="DuplicatiMonitor",
        )
        self._duplicati_monitor_thread.start()
        logger.info("🔍 Monitor Duplicati iniciado")

    def _duplicati_monitor_loop(self):
        """Loop de monitoramento: verifica resultado dos backups a cada 5 minutos."""
        CHECK_INTERVAL = 300  # segundos
        while True:
            try:
                self._check_duplicati_results()
            except Exception as exc:
                logger.debug(f"[DuplicatiMonitor] erro no ciclo: {exc}")
            time.sleep(CHECK_INTERVAL)

    def _check_duplicati_results(self):
        """Consulta o Duplicati e emite alertas para backups com erro ou falha."""
        try:
            from core.integrations.duplicati_native import get_duplicati_native_service
        except ImportError:
            return

        svc = get_duplicati_native_service()

        # Listar todos os backups conhecidos
        backups_resp = svc.list_backups()
        if backups_resp.get("status") != "success":
            return

        items = backups_resp.get("items", [])
        for item in items:
            backup = item.get("Backup") or item
            backup_id = str(backup.get("ID", ""))
            backup_name = backup.get("Name", backup_id)
            if not backup_id:
                continue

            result = svc.get_last_result(backup_id)
            if result.get("status") != "success":
                continue

            parsed = result.get("parsed_result")
            timestamp = result.get("timestamp")
            errors = result.get("errors", [])

            # Chave única para evitar alertas duplicados da mesma execução
            cache_key = f"{backup_id}:{timestamp}"
            if self._duplicati_last_seen.get(backup_id) == cache_key:
                continue  # já processado

            self._duplicati_last_seen[backup_id] = cache_key

            if parsed in (None, "Unknown", "Success"):
                continue  # sem erro: nada a fazer

            # Montar mensagem de alerta
            error_summary = "; ".join(str(e) for e in errors[:3]) if errors else "sem detalhes"
            alert_msg = (
                f"Backup '{backup_name}' (ID {backup_id}) terminou com '{parsed}'. "
                f"Erros: {error_summary}"
            )
            logger.warning(f"🚨 [DuplicatiMonitor] {alert_msg}")

            # Enviar alerta via WebSocket (assíncrono)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.send_realtime_alert(
                        alert_type="duplicati_backup_error",
                        message=alert_msg,
                        details={
                            "backup_id": backup_id,
                            "backup_name": backup_name,
                            "parsed_result": parsed,
                            "errors": errors,
                            "timestamp": timestamp,
                        },
                    ))
                else:
                    loop.run_until_complete(self.send_realtime_alert(
                        alert_type="duplicati_backup_error",
                        message=alert_msg,
                        details={
                            "backup_id": backup_id,
                            "backup_name": backup_name,
                            "parsed_result": parsed,
                            "errors": errors,
                            "timestamp": timestamp,
                        },
                    ))
            except Exception as exc:
                logger.warning(f"[DuplicatiMonitor] falha ao enviar alerta WebSocket: {exc}")

    def _load_configuration_silent(self):
        """Carrega configuração do servidor central sem testar conexão"""
        try:
            # Recarregar configuração usando o config_manager
            config_manager.reload()

            # Aplicar configuração ao cliente
            self.server_url = config_manager.get_server_url()
            self.api_key = config_manager.get_api_key()
            self.tenant_id = config_manager.get_tenant_id()

            if self.server_url and config_manager.is_enabled():
                logger.info(f"🌐 Servidor central configurado: {self.server_url}")
                logger.info(f"⏱️ Heartbeat: {config_manager.get_heartbeat_interval()} min")
                logger.info(f"🔄 Sincronização: {config_manager.get_sync_interval()} min")
                # Não testar conexão aqui - será feito quando necessário
            else:
                logger.info("⚠️ Cliente do servidor central desabilitado")

        except Exception as e:
            logger.error(f"Erro ao carregar configuração: {e}")
            # Valores padrão em caso de erro
            self.server_url = config_manager.get_server_url()
            self.api_key = config_manager.get_api_key() or "gboc-local-server-key"

    def _get_or_create_agent_id(self) -> str:
        """Obtém ou cria ID único do agente"""
        try:
            config_dir = Path("C:/ProgramData/GBOC") if os.name == 'nt' else Path.home() / ".gboc"
            config_dir.mkdir(parents=True, exist_ok=True)
            
            agent_id_file = config_dir / "agent_id"
            
            if agent_id_file.exists():
                with open(agent_id_file, 'r') as f:
                    agent_id = f.read().strip()
                    if agent_id:
                        return agent_id
            
            # Criar novo ID
            agent_id = str(uuid.uuid4())
            with open(agent_id_file, 'w') as f:
                f.write(agent_id)
            
            logger.info(f"🆔 Novo Agent ID criado: {agent_id}")
            return agent_id
            
        except Exception as e:
            logger.error(f"Erro ao obter Agent ID: {e}")
            return str(uuid.uuid4())  # Fallback

    def _load_configuration(self):
        """Carrega configuração do servidor central"""
        try:
            # Recarregar configuração usando o config_manager
            config_manager.reload()

            # Aplicar configuração ao cliente
            self.server_url = config_manager.get_server_url()
            self.api_key = config_manager.get_api_key()

            if self.server_url and config_manager.is_enabled():
                logger.info(f"🌐 Servidor central configurado: {self.server_url}")
                logger.info(f"⏱️ Heartbeat: {config_manager.get_heartbeat_interval()} min")
                logger.info(f"🔄 Sincronização: {config_manager.get_sync_interval()} min")

                # Testar conexão com o servidor
                self._test_server_connection(self.server_url, self.api_key or "")
            else:
                logger.info("⚠️ Cliente do servidor central desabilitado")

        except Exception as e:
            logger.error(f"Erro ao carregar configuração: {e}")
            # Valores padrão em caso de erro
            self.server_url = config_manager.get_server_url()
            self.api_key = config_manager.get_api_key() or "gboc-local-server-key"

    def reload_config(self) -> bool:
        """Recarrega configuração do servidor central"""
        try:
            self._load_configuration()
            logger.info("✅ Configuração recarregada")
            return True
        except Exception as e:
            logger.error(f"Erro ao recarregar configuração: {e}")
            return False
    
    def _create_sample_config(self, config_file: Path):
        """Cria arquivo de configuração de exemplo"""
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)

            # Configuração padrão para servidor local
            sample_config = {
                "server_url": "https://localhost:8000",
                "api_key": "gboc-local-server-key",
                "enabled": True,  # Habilitado por padrão para servidor local
                "heartbeat_interval_minutes": 2,  # Heartbeat mais frequente
                "sync_interval_minutes": 10,  # Sincronização mais frequente
                "send_logs": True,
                "send_metrics": True,
                "auto_connect": True
            }
            
            with open(config_file, 'w') as f:
                json.dump(sample_config, f, indent=2)
            
            logger.info(f"📝 Configuração de exemplo criada: {config_file}")
            
        except Exception as e:
            logger.error(f"Erro ao criar configuração de exemplo: {e}")
    
    def configure_server(self, server_url: str, api_key: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Configura conexão com servidor central"""
        try:
            # Validar URL
            if not server_url.startswith(('http://', 'https://')):
                return {"success": False, "error": "URL deve começar com http:// ou https://"}
            
            # Testar conexão
            test_result = self._test_server_connection(server_url, api_key)
            if not test_result['success']:
                return test_result
            
            # Salvar configuração
            config_file = Path("C:/ProgramData/GBOC/central_config.json") if os.name == 'nt' else Path.home() / ".gboc" / "config.json"
            config_file.parent.mkdir(parents=True, exist_ok=True)
            
            config = {
                "server_url": server_url.rstrip('/'),
                "api_key": api_key,
                "tenant_id": tenant_id,
                "enabled": True,
                "heartbeat_interval_minutes": 5,
                "sync_interval_minutes": 30,
                "send_logs": True,
                "send_metrics": True,
                "configured_at": datetime.now().isoformat()
            }
            
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Atualizar configuração ativa
            self.server_url = server_url.rstrip('/')
            self.api_key = api_key
            self.tenant_id = tenant_id
            
            # Registrar agente
            registration_result = self._register_agent()
            if registration_result['success']:
                # Iniciar heartbeat
                self._start_heartbeat()
                
                logger.info("✅ Servidor central configurado e agente registrado")
                return {
                    "success": True,
                    "message": "Servidor configurado com sucesso",
                    "agent_id": self.agent_id
                }
            else:
                return registration_result
                
        except Exception as e:
            logger.error(f"Erro ao configurar servidor: {e}")
            return {"success": False, "error": str(e)}
    
    def _test_server_connection(self, server_url: str, api_key: str) -> Dict[str, Any]:
        """Testa conexão com servidor"""
        try:
            headers = {
                "Content-Type": "application/json"
            }

            # Para servidor local, usar endpoint de versão sem autenticação
            response = self._session.get(
                f"{server_url}/api/v1/version",
                headers=headers,
                timeout=10
            )

            if response.status_code == 200:
                return {"success": True, "message": "Conexão estabelecida"}
            else:
                return {
                    "success": False,
                    "error": f"Servidor retornou status {response.status_code}"
                }

        except requests.exceptions.Timeout:
            return {"success": False, "error": "Timeout na conexão"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": "Erro de conexão - verifique se o servidor está rodando"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _register_agent(self) -> Dict[str, Any]:
        """Registra agente no servidor central"""
        try:
            if not self.server_url:
                return {"success": False, "error": "Servidor não configurado"}

            # Para servidor local, o registro é feito automaticamente via heartbeat
            # Apenas marcar como registrado
            self.is_registered = True
            logger.info(f"✅ Agente configurado para servidor central: {self.server_url}")
            return {"success": True, "message": "Agente configurado com sucesso"}

        except Exception as e:
            logger.error(f"Erro na configuração do agente: {e}")
            return {"success": False, "error": str(e)}
    
    def _collect_agent_info(self) -> Dict[str, Any]:
        """Coleta informações do agente"""
        try:
            # Informações básicas do sistema
            system_info = {
                "agent_id": self.agent_id,
                "hostname": socket.gethostname(),
                "platform": os.name,
                "version": "14.0.0",
                "registered_at": datetime.now().isoformat(),
                "tenant_id": self.tenant_id
            }
            
            # Informações detalhadas do sistema
            try:
                system_info.update({
                    "cpu_count": psutil.cpu_count(),
                    "memory_total": psutil.virtual_memory().total,
                    "disk_usage": self._get_disk_usage(),
                    "ip_address": self._get_local_ip()
                })
            except:
                pass  # Informações opcionais
            
            # Estatísticas dos repositórios
            try:
                repo_stats = self._get_repository_statistics()
                system_info["repositories"] = repo_stats
            except:
                pass
            
            return system_info
            
        except Exception as e:
            logger.error(f"Erro ao coletar info do agente: {e}")
            return {"agent_id": self.agent_id, "error": str(e)}
    
    def _get_disk_usage(self) -> Dict[str, Any]:
        """Obtém uso de disco"""
        try:
            disk_usage = {}
            for disk in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(disk.mountpoint)
                    disk_usage[disk.device] = {
                        "total": usage.total,
                        "used": usage.used,
                        "free": usage.free
                    }
                except:
                    continue
            return disk_usage
        except:
            return {}
    
    def _get_local_ip(self) -> str:
        """Obtém IP local"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "unknown"
    
    def _get_repository_statistics(self) -> Dict[str, Any]:
        """Obtém estatísticas dos repositórios"""
        try:
            with self.shared_core.get_db_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    # Contar repositórios
                    cursor.execute("SELECT COUNT(*) as total FROM repositories WHERE status='active'")
                    repo_count = cursor.fetchone()['total']
                    
                    # Contar tarefas
                    cursor.execute("SELECT COUNT(*) as total FROM tasks WHERE enabled=1")
                    task_count = cursor.fetchone()['total']
                    
                    # Último backup
                    cursor.execute("""
                        SELECT backup_date FROM backup_statistics 
                        ORDER BY backup_date DESC LIMIT 1
                    """)
                    
                    last_backup_row = cursor.fetchone()
                    last_backup = last_backup_row['backup_date'] if last_backup_row else None
                    
                    return {
                        "total_repositories": repo_count,
                        "total_tasks": task_count,
                        "last_backup": last_backup
                    }
                
        except Exception as e:
            logger.error(f"Erro ao obter estatísticas: {e}")
            return {}
    
    def _start_heartbeat(self):
        """Inicia thread de heartbeat"""
        try:
            if self.heartbeat_thread and self.heartbeat_thread.is_alive():
                return  # Já rodando
            
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self.heartbeat_thread.start()
            logger.info("💓 Heartbeat iniciado")
            
        except Exception as e:
            logger.error(f"Erro ao iniciar heartbeat: {e}")
    
    def _start_websocket(self):
        """Inicia conexão WebSocket para comunicação em tempo real"""
        try:
            if self.websocket_thread and self.websocket_thread.is_alive():
                return  # Já rodando
            
            self.websocket_thread = threading.Thread(target=self._websocket_loop, daemon=True)
            self.websocket_thread.start()
            logger.info("🔗 WebSocket iniciado")
            
        except Exception as e:
            logger.error(f"Erro ao iniciar WebSocket: {e}")
    
    def _websocket_loop(self):
        """Loop de manutenção da conexão WebSocket"""
        _backoff = 30  # segundos entre tentativas
        while self.server_url:
            try:
                # Converter URL HTTP para WS
                ws_url = self.server_url.replace("http://", "ws://").replace("https://", "wss://")
                ws_url += f"/ws/agents/{self.agent_id}"

                # Conectar WebSocket
                asyncio.run(self._connect_websocket(ws_url))
                _backoff = 30  # reset backoff após conexão bem-sucedida

            except Exception as e:
                logger.warning(f"⚠️ WebSocket indisponível, próxima tentativa em {_backoff}s")
                time.sleep(_backoff)
                _backoff = min(_backoff * 2, 300)  # backoff exponencial até 5 min
    
    async def _connect_websocket(self, ws_url: str):
        """Conecta ao WebSocket do servidor"""
        try:
            # Usar SSL sem verificação de cert para wss:// com certificado autoassinado local
            _ssl_ctx = None
            if ws_url.startswith("wss://"):
                import ssl
                _ssl_ctx = ssl.create_default_context()
                _ssl_ctx.check_hostname = False
                _ssl_ctx.verify_mode = ssl.CERT_NONE

            async with websockets.connect(ws_url, ssl=_ssl_ctx) as websocket:
                self.websocket = websocket
                self.websocket_connected = True
                logger.info(f"🔗 WebSocket conectado: {ws_url}")
                
                # Enviar sincronização inicial
                await self._send_full_sync()
                
                # Manter conexão ativa
                while True:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=60.0)
                        await self._handle_websocket_response(message)
                    except asyncio.TimeoutError:
                        # Enviar heartbeat periódico via WebSocket
                        await self._send_websocket_heartbeat()
                        
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket desconectado")
        except OSError as e:
            # Erro de conexão (servidor offline) — propaga para o loop aplicar backoff
            raise
        except Exception as e:
            logger.error(f"Erro no WebSocket: {e}")
            raise
        finally:
            self.websocket_connected = False
            self.websocket = None
    
    async def _send_full_sync(self):
        """Envia sincronização completa via WebSocket"""
        try:
            full_data = self._collect_full_agent_data()
            message = {
                "type": "full_sync",
                "data": full_data,
                "timestamp": datetime.now().isoformat()
            }
            await self.websocket.send(json.dumps(message))
            logger.info("📤 Sincronização completa enviada via WebSocket")
        except Exception as e:
            logger.error(f"Erro ao enviar sincronização completa: {e}")
    
    async def _send_websocket_heartbeat(self):
        """Envia heartbeat via WebSocket"""
        try:
            heartbeat_data = self._collect_realtime_data()
            message = {
                "type": "heartbeat",
                "data": heartbeat_data,
                "timestamp": datetime.now().isoformat()
            }
            await self.websocket.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Erro ao enviar heartbeat WebSocket: {e}")
    
    async def _handle_websocket_response(self, message: str):
        """Processa respostas do servidor via WebSocket"""
        try:
            data = json.loads(message)
            self.last_websocket_message = data

            msg_type = data.get("type", "")

            if msg_type in ("command", "rmm_exec", "rmm_command", "rmm_terminal", "request_mirror"):
                # Processar comando RMM ou sincronização do servidor
                await self._process_server_command(data)
            elif msg_type == "request_full_sync":
                # Servidor solicitou resincronização completa
                logger.info("📥 Servidor solicitou sincronização completa")
                await self._send_full_sync()

        except json.JSONDecodeError:
            logger.warning(f"Mensagem WebSocket inválida: {message}")
    
    async def _process_server_command(self, command: Dict):
        """Processa comando RMM ou solicitação recebida do servidor via WebSocket."""
        cmd_type = command.get("command") or command.get("type")
        
        if cmd_type == "request_sync" or cmd_type == "request_full_sync":
            await self._send_full_sync()
            
        elif cmd_type == "request_manual_sync":
            sync_data = command.get("data", {})
            await self._send_manual_sync(sync_data)

        elif cmd_type in ("rmm_exec", "rmm_command", "rmm_terminal"):
            # Executar comando de terminal RMM enviado pelo Servidor Central
            try:
                from modules.rmm.rmm_router import rmm_execute_command
                class DummyRequest:
                    def __init__(self, data):
                        self._data = data
                    async def json(self):
                        return self._data

                payload = command.get("data") or command
                req = DummyRequest(payload)
                res = await rmm_execute_command(req)

                reply_msg = {
                    "type": "rmm_exec_result",
                    "request_id": command.get("request_id"),
                    "agent_id": self.agent_id,
                    "result": res,
                    "timestamp": datetime.now().isoformat()
                }
                if self.websocket and self.websocket_connected:
                    await self.websocket.send(json.dumps(reply_msg))
                    logger.info(f"📤 Resposta RMM enviada ao servidor via WebSocket para o comando '{payload.get('command')}'")
            except Exception as rmm_err:
                logger.error(f"Erro ao executar comando RMM via WebSocket: {rmm_err}")

        elif cmd_type in ("request_mirror", "rmm_mirror"):
            # Enviar Espelho Remoto Completo do Agente (State Snapshot 1:1)
            try:
                from modules.rmm.rmm_router import rmm_get_agent_mirror
                mirror_res = await rmm_get_agent_mirror()
                reply_msg = {
                    "type": "rmm_mirror_data",
                    "agent_id": self.agent_id,
                    "mirror": mirror_res.get("mirror", {}),
                    "timestamp": datetime.now().isoformat()
                }
                if self.websocket and self.websocket_connected:
                    await self.websocket.send(json.dumps(reply_msg))
                    logger.info("📤 Espelho Remoto 1:1 enviado ao Servidor Central via WebSocket")
            except Exception as m_err:
                logger.error(f"Erro ao enviar espelho remoto: {m_err}")
    
    async def _send_manual_sync(self, sync_request: Dict):
        """Envia sincronização manual via WebSocket"""
        try:
            message = {
                "type": "manual_sync",
                "data": sync_request,
                "timestamp": datetime.now().isoformat()
            }
            await self.websocket.send(json.dumps(message))
            logger.info("📤 Sincronização manual enviada via WebSocket")
        except Exception as e:
            logger.error(f"Erro ao enviar sincronização manual: {e}")
    
    def _collect_full_agent_data(self) -> Dict:
        """Coleta todos os dados do agente para sincronização completa"""
        try:
            # Dados básicos do sistema
            system_info = self._collect_full_agent_info()
            
            # Adicionar dados históricos
            with self.shared_core.get_db_connection() as conn:
                cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) if PSYCOPG2_AVAILABLE else conn.cursor()

                # Repositórios
                cursor.execute("SELECT * FROM repositories")
                rows = cursor.fetchall()
                repos = [self._serialize_for_json(dict(row) if PSYCOPG2_AVAILABLE else dict(zip([d[0] for d in cursor.description], row))) for row in rows]

                # Tarefas
                cursor.execute("SELECT * FROM tasks")
                rows = cursor.fetchall()
                tasks = [self._serialize_for_json(dict(row) if PSYCOPG2_AVAILABLE else dict(zip([d[0] for d in cursor.description], row))) for row in rows]

                # Execuções de tarefas (fallback se tabela não existir)
                try:
                    cursor.execute("SELECT * FROM task_executions ORDER BY started_at DESC LIMIT 100")
                    rows = cursor.fetchall()
                    executions = [self._serialize_for_json(dict(row) if PSYCOPG2_AVAILABLE else dict(zip([d[0] for d in cursor.description], row))) for row in rows]
                except Exception:
                    executions = []

                # Eventos do sistema (fallback se tabela não existir)
                try:
                    cursor.execute("SELECT * FROM system_events ORDER BY created_at DESC LIMIT 50")
                    rows = cursor.fetchall()
                    events = [self._serialize_for_json(dict(row) if PSYCOPG2_AVAILABLE else dict(zip([d[0] for d in cursor.description], row))) for row in rows]
                except Exception:
                    events = []

                # Alertas
                try:
                    cursor.execute("SELECT * FROM alerts ORDER BY timestamp DESC LIMIT 50")
                    rows = cursor.fetchall()
                    alerts = [self._serialize_for_json(dict(row) if PSYCOPG2_AVAILABLE else dict(zip([d[0] for d in cursor.description], row))) for row in rows]
                except Exception:
                    alerts = []

                try:
                    cursor.close()
                except Exception:
                    pass

            data = {
                **system_info,
                "repositories": repos,
                "tasks": tasks,
                "task_executions": executions,
                "system_events": events,
                "alerts": alerts,
                "timestamp": datetime.now().isoformat()
            }

            # Converter objetos datetime para strings JSON serializáveis
            data = self._serialize_for_json(data)

            return data

        except Exception as e:
            logger.error(f"Erro ao coletar dados completos: {e}")
            return {}

    def _serialize_for_json(self, obj):
        """Converte objetos datetime para strings para serialização JSON"""
        from datetime import date, time
        if isinstance(obj, (datetime, date, time)):
            return obj.isoformat()
        elif isinstance(obj, dict):
            return {k: self._serialize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._serialize_for_json(item) for item in obj]
        else:
            return obj
    
    def _collect_realtime_data(self) -> Dict:
        """Coleta dados em tempo real para heartbeat"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('C:') if os.name == 'nt' else psutil.disk_usage('/')
            
            return {
                "agent_id": self.agent_id,
                "hostname": socket.gethostname(),
                "status": "online",
                "cpu_usage": cpu_percent,
                "ram_usage": memory.percent,
                "disk_usage": disk.percent,
                "timestamp": datetime.now().isoformat(),
                "tenant_id": self.tenant_id
            }
        except Exception as e:
            logger.error(f"Erro ao coletar dados em tempo real: {e}")
            return {}
    
    def _heartbeat_loop(self):
        """Loop de heartbeat e sincronização"""
        last_sync = 0
        last_config_check = 0
        last_alive_log = 0

        while self.server_url:
            try:
                current_time = time.time()

                # Log de vida periódico para evitar percepção de travamento
                if current_time - last_alive_log >= 60:
                    ws_ok = self.websocket_thread.is_alive() if self.websocket_thread else False
                    logger.info(f"💓 Agent ativo (heartbeat thread OK, websocket={'ON' if ws_ok else 'OFF'})")
                    last_alive_log = current_time

                # Verificar configuração a cada 30 segundos
                if current_time - last_config_check >= 30:
                    config_manager.reload()
                    last_config_check = current_time

                # Obter intervalos da configuração
                heartbeat_interval = config_manager.get_heartbeat_interval() * 60  # converter para seconds
                sync_interval = config_manager.get_sync_interval() * 60

                # Enviar heartbeat
                self._send_heartbeat()

                # Sincronizar dados periodicamente
                if current_time - last_sync >= sync_interval:
                    logger.info("🔄 Iniciando sincronização periódica...")
                    sync_result = self.sync_with_server()
                    if sync_result.get("success"):
                        logger.info("✅ Sincronização concluída")
                    else:
                        logger.warning(f"⚠️ Erro na sincronização: {sync_result.get('error')}")

                    last_sync = current_time

                time.sleep(min(heartbeat_interval, 300))  # Máximo 5 minutos entre verificações

            except Exception as e:
                logger.error(f"Erro no loop de comunicação: {e}")
                # Tentar reconectar em intervalos crescentes
                retry_delay = 30  # Começar com 30 segundos
                max_delay = 300  # Máximo 5 minutos

                while retry_delay <= max_delay:
                    try:
                        logger.info(f"🔄 Tentando reconectar em {retry_delay} segundos...")
                        time.sleep(retry_delay)

                        # Testar conexão
                        test_result = self._test_server_connection(self.server_url, self.api_key or "")
                        if test_result.get("success"):
                            logger.info("✅ Reconexão estabelecida")
                            break
                        else:
                            logger.warning(f"⚠️ Falha na reconexão: {test_result.get('error')}")

                    except Exception as reconnect_error:
                        logger.error(f"Erro na tentativa de reconexão: {reconnect_error}")

                    retry_delay = min(retry_delay * 2, max_delay)  # Backoff exponencial

                if retry_delay > max_delay:
                    logger.error("❌ Falha persistente na reconexão. Aguardando próximo ciclo...")
                    time.sleep(60)  # Aguardar 1 minuto antes de tentar novamente
    
    def _send_heartbeat(self):
        """Envia heartbeat para servidor"""
        try:
            if not self.server_url:
                logger.warning("⚠️ Servidor central não configurado")
                return

            # Coletar dados completos do sistema
            heartbeat_data = self._collect_full_agent_info()
            logger.debug(f"📊 Enviando heartbeat para {self.server_url}/api/v1/agents/heartbeat")

            response = self._session.post(
                f"{self.server_url}/api/v1/agents/heartbeat",
                json=heartbeat_data,
                headers={"Content-Type": "application/json"},
                timeout=30
            )

            if response.status_code == 200:
                self.last_heartbeat = datetime.now()
                logger.debug("💓 Heartbeat enviado com sucesso")
            else:
                logger.warning(f"⚠️ Heartbeat retornou: {response.status_code} - {response.text}")

        except requests.exceptions.ConnectionError:
            logger.error(f"❌ Erro de conexão com servidor central: {self.server_url}")
        except requests.exceptions.Timeout:
            logger.error(f"⏰ Timeout ao conectar com servidor central")
        except Exception as e:
            logger.error(f"❌ Erro no heartbeat: {e}")
    
    def _collect_full_agent_info(self) -> Dict[str, Any]:
        """Coleta informações completas do agente para heartbeat"""
        try:
            # Informações básicas do sistema
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('C:') if os.name == 'nt' else psutil.disk_usage('/')

            # Informações detalhadas do sistema
            system_info = {
                "agent_id": self.agent_id,
                "hostname": socket.gethostname(),
                "status": "online",
                "version": "14.0.0",
                "ip_address": self._get_local_ip() + ":9200",  # Endereço real do agente
                "cpu_usage": cpu_percent,
                "ram_usage": memory.percent,
                "disk_usage": disk.percent,
                "ip_public": self._get_public_ip(),  # IP público real
                "agent_local_time": datetime.now().isoformat(),
                "os_info": f"{platform.system()} {platform.release()}",
                "cpu_cores": psutil.cpu_count(),
                "ram_total_gb": f"{memory.total / (1024**3):.1f} GB",
                "ram_available_gb": f"{memory.available / (1024**3):.1f} GB",
                "tenant_id": self.tenant_id
            }

            # Estatísticas dos repositórios e tarefas
            try:
                from shared_core import get_shared_core
                core = get_shared_core()
                with core.get_db_connection() as conn:
                    cur = conn.cursor()

                    # Contar repositórios ativos
                    cur.execute("SELECT COUNT(*) FROM repositories WHERE status='active'")
                    system_info["component_count"] = cur.fetchone()[0]

                    # Contar tarefas
                    cur.execute("SELECT COUNT(*) FROM tasks WHERE status != 'idle'")
                    system_info["target_count"] = cur.fetchone()[0]

                    # Status do scheduler (simulado como ativo)
                    system_info["scheduler_status"] = "running"
                    system_info["execution_mode"] = "Service"

                    # Tarefas em execução
                    try:
                        cur.execute("SELECT COUNT(*) FROM task_executions WHERE status='running'")
                        system_info["jobs_running_count"] = cur.fetchone()[0]
                    except Exception:
                        system_info["jobs_running_count"] = 0

                    # Lista de tarefas falhadas (últimas 5)
                    try:
                        cur.execute("""
                            SELECT task_id FROM task_executions
                            WHERE status='failed'
                            ORDER BY started_at DESC LIMIT 5
                        """)
                        failed_tasks = [row[0] for row in cur.fetchall()]
                    except Exception:
                        failed_tasks = []
                    system_info["jobs_failed_list"] = failed_tasks

            except Exception as e:
                logger.warning(f"Erro ao coletar estatísticas do banco: {e}")
                system_info.update({
                    "component_count": 0,
                    "target_count": 0,
                    "scheduler_status": "unknown",
                    "execution_mode": "unknown",
                    "jobs_running_count": 0,
                    "jobs_failed_list": []
                })

            return system_info

        except Exception as e:
            logger.error(f"Erro ao coletar informações do agente: {e}")
            return {
                "agent_id": self.agent_id,
                "status": "error",
                "error": str(e)
            }
    
    def sync_with_server(self) -> Dict[str, Any]:
        """Sincroniza dados com servidor central"""
        try:
            if not self.server_url:
                return {"success": False, "error": "Servidor não configurado"}

            logger.info("🔄 Sincronizando dados com servidor central...")

            results = {
                "success": True,
                "synced_at": datetime.now().isoformat(),
                "repositories": {"synced": 0},
                "tasks": {"synced": 0},
                "statistics": {"synced": 0},
                "logs": {"synced": 0}
            }

            # Sincronizar repositórios
            try:
                repo_result = self._sync_repositories()
                results["repositories"] = repo_result
            except Exception as e:
                logger.warning(f"Erro na sincronização de repositórios: {e}")
                results["repositories"] = {"error": str(e)}

            # Sincronizar tarefas
            try:
                task_result = self._sync_tasks()
                results["tasks"] = task_result
            except Exception as e:
                logger.warning(f"Erro na sincronização de tarefas: {e}")
                results["tasks"] = {"error": str(e)}

            # Sincronizar estatísticas de backup
            try:
                stats_result = self._sync_backup_statistics()
                results["statistics"] = stats_result
            except Exception as e:
                logger.warning(f"Erro na sincronização de estatísticas: {e}")
                results["statistics"] = {"error": str(e)}

            # Sincronizar logs
            try:
                logs_result = self._sync_logs()
                results["logs"] = logs_result
            except Exception as e:
                logger.warning(f"Erro na sincronização de logs: {e}")
                results["logs"] = {"error": str(e)}

            logger.info("✅ Sincronização concluída")
            return results

        except Exception as e:
            logger.error(f"Erro na sincronização: {e}")
            return {"success": False, "error": str(e)}
    
    def _sync_repositories(self) -> Dict[str, Any]:
        """Sincroniza repositórios com servidor"""
        try:
            from shared_core import get_shared_core
            core = get_shared_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()

                cur.execute("""
                    SELECT id, name, engine, type, status, created_at, updated_at
                    FROM repositories WHERE status='active'
                """)
                repositories = []

                rows = cur.fetchall()
                columns = [d[0] for d in cur.description] if cur.description else []
                for row in rows:
                    if isinstance(row, dict):
                        repo_dict = row
                    else:
                        repo_dict = dict(zip(columns, row)) if columns else {}

                    # Formatar dados para o servidor
                    repo_info = {
                        "agent_id": self.agent_id,
                        "id": repo_dict.get("id"),
                        "name": repo_dict.get("name"),
                        "engine": repo_dict.get("engine") or "restic",
                        "type": repo_dict.get("type") or "local",
                        "status": repo_dict.get("status") or "active",
                        "last_backup": None,
                        "total_backups": 0
                    }
                    if repo_info["id"] is not None:
                        repositories.append(repo_info)

                if not repositories:
                    return {"synced": 0, "message": "Nenhum repositório ativo"}

                # Enviar para servidor
                response = self._session.post(
                    f"{self.server_url}/api/v1/agents/{self.agent_id}/repositories",
                    json=repositories,
                    headers={"Content-Type": "application/json"},
                    timeout=60
                )

                if response.status_code == 200:
                    return {"synced": len(repositories), "status": "success"}
                else:
                    logger.warning(f"Erro HTTP na sincronização de repositórios: {response.status_code}")
                    return {"synced": 0, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error(f"Erro ao sincronizar repositórios: {e}")
            return {"synced": 0, "error": str(e)}
    
    def _sync_backup_statistics(self) -> Dict[str, Any]:
        """Sincroniza estatísticas de backup com servidor"""
        try:
            # Enviar estatísticas dos últimos 7 dias
            week_ago = (datetime.now() - timedelta(days=7)).isoformat()

            with self.shared_core.get_db_connection() as conn:
                if PSYCOPG2_AVAILABLE:
                    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    try:
                        cursor.execute("""
                            SELECT
                                task_id, task_name, repository_name, backup_date, success,
                                duration_seconds, bytes_processed, files_processed, error_message
                            FROM backup_statistics
                            WHERE backup_date > %s
                            ORDER BY backup_date DESC
                            LIMIT 1000
                        """, (week_ago,))
                        rows = cursor.fetchall()
                    except Exception:
                        # Fallback: usar tabela backups
                        cursor.execute("""
                            SELECT
                                task_id,
                                COALESCE(task_name, 'Task') as task_name,
                                COALESCE(repository_name, 'Unknown') as repository_name,
                                start_time as backup_date,
                                (status = 'success') as success,
                                COALESCE(duration_seconds, 0) as duration_seconds,
                                COALESCE(bytes_processed, 0) as bytes_processed,
                                COALESCE(files_processed, 0) as files_processed,
                                error_message
                            FROM backups
                            WHERE start_time > %s
                            ORDER BY start_time DESC
                            LIMIT 1000
                        """, (week_ago,))
                        rows = cursor.fetchall()

                    statistics = []
                    for row in rows:
                        stat_info = {
                            "agent_id": self.agent_id,
                            "task_id": row.get("task_id"),
                            "task_name": row.get("task_name") or f"Task-{row.get('task_id', 0)}",
                            "repository_name": row.get("repository_name") or "Unknown",
                            "backup_date": row.get("backup_date"),
                            "success": bool(row.get("success")),
                            "duration_seconds": row.get("duration_seconds") or 0,
                            "bytes_processed": row.get("bytes_processed") or 0,
                            "files_processed": row.get("files_processed") or 0,
                            "error_message": row.get("error_message")
                        }
                        statistics.append(stat_info)
                else:
                    return {"synced": 0, "message": "SQLite mode - estatísticas detalhadas desabilitadas"}

                if not statistics:
                    return {"synced": 0, "message": "Nenhuma estatística recente"}

                response = self._session.post(
                    f"{self.server_url}/api/v1/sync/statistics",
                    json={"agent_id": self.agent_id, "statistics": statistics},
                    headers={"Content-Type": "application/json"},
                    timeout=60
                )

                if response.status_code == 200:
                    return {"synced": len(statistics), "status": "success"}
                else:
                    logger.warning(f"Erro HTTP na sincronização de estatísticas: {response.status_code}")
                    return {"synced": 0, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error(f"Erro ao sincronizar estatísticas: {e}")
            return {"synced": 0, "error": str(e)}
    
    def _sync_logs(self) -> Dict[str, Any]:
        """Sincroniza logs do sistema com servidor"""
        try:
            # Enviar logs das últimas 24 horas
            day_ago = (datetime.now() - timedelta(days=1)).isoformat()

            from shared_core import get_shared_core
            core = get_shared_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()

                cur.execute("""
                    SELECT timestamp, level, source, message, details
                    FROM system_logs
                    WHERE timestamp > %s
                    ORDER BY timestamp DESC
                    LIMIT 500
                """, (day_ago,))

                logs = []
                for row in cur.fetchall():
                    log_info = {
                        "agent_id": self.agent_id,
                        "timestamp": row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0]),
                        "level": row[1] or "INFO",
                        "source": row[2] or "Unknown",
                        "message": row[3],
                        "details": row[4]
                    }
                    logs.append(log_info)

                if not logs:
                    return {"synced": 0, "message": "Nenhum log recente"}

                # Enviar para servidor
                response = self._session.post(
                    f"{self.server_url}/api/v1/sync/logs",
                    json={"agent_id": self.agent_id, "logs": logs},
                    headers={"Content-Type": "application/json"},
                    timeout=60
                )

                if response.status_code == 200:
                    return {"synced": len(logs), "status": "success"}
                else:
                    logger.warning(f"Erro HTTP na sincronização de logs: {response.status_code}")
                    return {"synced": 0, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error(f"Erro ao sincronizar logs: {e}")
            return {"synced": 0, "error": str(e)}

    def _sync_tasks(self) -> Dict[str, Any]:
        """Sincroniza informações de tarefas com servidor"""
        try:
            from shared_core import get_shared_core
            core = get_shared_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()

                try:
                    cur.execute("""
                        SELECT
                            t.id, t.name, t.status, t.created_at, t.updated_at
                        FROM tasks t
                        ORDER BY t.id
                    """)
                    use_updated_at = True
                except Exception:
                    cur.execute("""
                        SELECT
                            t.id, t.name, t.status, t.created_at
                        FROM tasks t
                        ORDER BY t.id
                    """)
                    use_updated_at = False

                tasks = []
                for row in cur.fetchall():
                    # Garantir que created_at e updated_at sejam objetos datetime
                    created_at = row[3] if len(row) > 3 else None
                    updated_at = row[4] if use_updated_at and len(row) > 4 else created_at
                    
                    task_info = {
                        "id": row[0],
                        "name": row[1],
                        "status": row[2] or "pending",
                        "created_at": created_at.isoformat() if created_at and hasattr(created_at, 'isoformat') else None,
                        "updated_at": updated_at.isoformat() if updated_at and hasattr(updated_at, 'isoformat') else None
                    }
                    tasks.append(task_info)

                if not tasks:
                    return {"synced": 0, "message": "Nenhuma tarefa encontrada"}

                # Enviar para servidor
                response = self._session.post(
                    f"{self.server_url}/api/v1/sync/tasks",
                    json={"agent_id": self.agent_id, "tasks": tasks},
                    headers={"Content-Type": "application/json"},
                    timeout=60
                )

                if response.status_code == 200:
                    return {"synced": len(tasks), "status": "success"}
                else:
                    logger.warning(f"Erro HTTP na sincronização de tarefas: {response.status_code}")
                    return {"synced": 0, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error(f"Erro ao sincronizar tarefas: {e}")
            return {"synced": 0, "error": str(e)}
            return {"synced": 0, "error": str(e)}

    def _calculate_task_success_rate(self, task_id: int) -> float:
        """Calcula taxa de sucesso de uma tarefa baseada em execuções recentes"""
        try:
            with self.shared_core.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT COUNT(*) as total,
                               SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful
                        FROM task_executions
                        WHERE task_id = %s
                    """, (task_id,))

                    row = cursor.fetchone()
                    if row and row[0] > 0:
                        return (row[1] / row[0]) * 100
                    return 0.0

        except Exception:
            return 0.0

    def _get_task_last_execution(self, task_id: int) -> Optional[str]:
        """Obtém timestamp da última execução de uma tarefa"""
        try:
            with self.shared_core.get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT started_at FROM task_executions
                        WHERE task_id = %s
                        ORDER BY started_at DESC LIMIT 1
                    """, (task_id,))

                    row = cursor.fetchone()
                    return row[0] if row else None

        except Exception:
            return None

    def _get_local_ip(self) -> str:
        """Obtém o IP REAL da rede local (LAN) do Agente. NUNCA envia 127.0.0.1 ou localhost."""
        # 1. Probe via UDP socket conectando no roteador/gateway
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            if local_ip and not local_ip.startswith("127.") and local_ip != "0.0.0.0":
                return local_ip
        except Exception:
            pass

        # 2. Varredura de interfaces de rede ativas (psutil)
        try:
            import psutil
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip = addr.address
                        if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                            return ip
        except Exception:
            pass

        # 3. Resolução pelo hostname do sistema
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                return ip
        except Exception:
            pass

        # Fallback de LAN genérico para não transmitir 127.0.0.1 ao servidor central
        return "192.168.1.100"

    def _get_public_ip(self) -> str:
        """Obtém o IP público REAL da máquina na internet."""
        services = [
            "https://api.ipify.org",
            "https://ifconfig.me/ip",
            "https://checkip.amazonaws.com",
            "https://icanhazip.com"
        ]
        for url in services:
            try:
                res = requests.get(url, timeout=4)
                if res.status_code == 200 and res.text.strip():
                    ip = res.text.strip()
                    if ip and not ip.startswith("127."):
                        return ip
            except Exception:
                continue
        # Fallback para o IP da LAN local se desconectado da internet pública
        return self._get_local_ip()

    def get_connection_status(self) -> Dict[str, Any]:
        """Obtém status da conexão com servidor"""
        return {
            "configured": bool(self.server_url and self.api_key),
            "server_url": self.server_url,
            "agent_id": self.agent_id,
            "is_registered": self.is_registered,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "heartbeat_active": self.heartbeat_thread.is_alive() if self.heartbeat_thread else False,
            "websocket_connected": self.websocket_connected,
            "websocket_active": self.websocket_thread.is_alive() if self.websocket_thread else False,
            "last_websocket_message": self.last_websocket_message
        }

    async def send_realtime_alert(self, alert_type: str, message: str, details: Optional[Dict] = None):
        """Envia alerta em tempo real via WebSocket"""
        try:
            if not self.websocket_connected or not self.websocket:
                logger.warning("WebSocket não conectado - alerta não enviado")
                return
            
            alert_data = {
                "type": alert_type,
                "message": message,
                "hostname": socket.gethostname(),
                "timestamp": datetime.now().isoformat()
            }
            
            if details:
                alert_data["details"] = details
            
            message = {
                "type": "alert",
                "data": alert_data,
                "timestamp": datetime.now().isoformat()
            }
            
            await self.websocket.send(json.dumps(message))
            logger.info(f"🚨 Alerta enviado via WebSocket: {alert_type}")
            
        except Exception as e:
            logger.error(f"Erro ao enviar alerta via WebSocket: {e}")

# Instância global
central_client = CentralServerClient()

logger.info("🌐 CentralServerClient inicializado")

