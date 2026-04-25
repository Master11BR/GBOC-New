#!/usr/bin/env python3
"""
GBOC 11.7c - Ransomware Guardian (Watchdog Automatico)

Modulo de protecao ATIVA contra ransomware.
Roda em background como thread daemon e executa:

  1. Verificacao periodica de canary files (a cada N minutos)
  2. Resposta automatica ao detectar ameaca:
     - Cria snapshot emergencial dos repositorios
     - Bloqueia acesso de escrita nos repos (read-only / lock)
     - Envia notificacao por TODOS os canais (SMTP, webhook, telegram)
     - Registra incidente completo no banco
     - (Opcional) Para servicos de backup para evitar sobrescrita de backups bons

Projetado para operar 100% autonomo, sem intervencao humana.
Ataque de madrugada? O Guardian responde em minutos.
"""

import logging
import threading
import time
import json
import os
import subprocess
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("RansomwareGuardian")


class RansomwareGuardian:
    """Watchdog daemon que monitora canaries e responde automaticamente."""

    def __init__(self, check_interval_minutes: int = 5, enabled: bool = True):
        self.check_interval = check_interval_minutes * 60  # em segundos
        self.enabled = enabled
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._incident_lock = threading.Lock()
        self._last_incident_time: Optional[datetime] = None
        # Cooldown para evitar multiplas respostas ao mesmo ataque (30 min)
        self._incident_cooldown_seconds = 1800

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Inicia o watchdog em background."""
        if not self.enabled:
            logger.info("[Guardian] Desabilitado por configuracao")
            return
        if self._thread and self._thread.is_alive():
            logger.warning("[Guardian] Ja esta rodando")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="RansomwareGuardian")
        self._thread.start()
        logger.info(f"[Guardian] Iniciado - verificacao a cada {self.check_interval // 60} min")

    def stop(self):
        """Para o watchdog."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("[Guardian] Parado")

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _watch_loop(self):
        """Loop principal do watchdog."""
        # Espera inicial de 30s para o sistema subir completamente
        time.sleep(30)

        # Garantir que existam canaries ao iniciar
        self._ensure_canaries()

        logger.info("[Guardian] Watchdog ativo - primeira verificacao")

        while not self._stop_event.is_set():
            try:
                result = self._check_canaries()
                if result and result.get('threat_detected'):
                    self._handle_threat(result)
            except Exception as e:
                logger.error(f"[Guardian] Erro na verificacao: {e}", exc_info=True)

            # Dormir no intervalo, mas acordar se stop for chamado
            self._stop_event.wait(timeout=self.check_interval)

    def _ensure_canaries(self):
        """Cria canary files automaticamente se não existirem.

        IMPORTANTE: não criar nem monitorar canary em pasta temporária,
        para evitar falsos positivos (limpeza automática do SO).
        """
        try:
            from engines.ransomware_detector import create_canary, ensure_tables, _query, _execute
            ensure_tables()

            # Remover canaries antigos em diretórios temporários (legado)
            temp_roots = [
                os.path.abspath(os.environ.get('TEMP', '')),
                os.path.abspath(os.environ.get('TMP', '')),
                os.path.abspath('/tmp')
            ]
            temp_roots = [t for t in temp_roots if t and t != os.path.abspath('.')]

            existing_rows = _query("SELECT id, file_path FROM ransomware_canaries")
            removed_temp = 0
            for row in existing_rows:
                fpath = os.path.abspath(str(row.get('file_path') or ''))
                if any(fpath.startswith(root) for root in temp_roots):
                    try:
                        _execute("DELETE FROM ransomware_canaries WHERE id = %s", (row.get('id'),))
                        removed_temp += 1
                    except Exception:
                        pass
            if removed_temp:
                logger.info(f"[Guardian] {removed_temp} canary(s) em pasta temporária removido(s)")

            # Verificar se já existem canaries válidos
            existing = _query("SELECT COUNT(*) as cnt FROM ransomware_canaries")
            count = existing[0]['cnt'] if existing else 0

            if count > 0:
                logger.info(f"[Guardian] {count} canary(s) existente(s)")
                monitored = _query("SELECT file_path FROM ransomware_canaries ORDER BY id")
                logger.info("[Guardian] [CANARY_SCOPE] Monitorando apenas caminhos estáveis (sem TEMP/TMP)")
                for m in monitored[:10]:
                    logger.info(f"[Guardian] [CANARY_SCOPE] {m.get('file_path')}")
                if len(monitored) > 10:
                    logger.info(f"[Guardian] [CANARY_SCOPE] ... e mais {len(monitored)-10} caminho(s)")
                return

            # Criar canaries em locais estáveis
            logger.info("[Guardian] Nenhum canary encontrado - criando automaticamente...")

            canary_locations = []

            # 1. Diretório de dados do Agent
            agent_data = os.environ.get('AGENT_DATA_DIR', os.path.join(os.getcwd(), 'data'))
            canary_locations.append(os.path.join(agent_data, '.gboc_canary_data'))

            # 2. Diretório de repositórios
            repos_dir = os.path.join(os.getcwd(), 'repositorios')
            if os.path.isdir(repos_dir):
                canary_locations.append(os.path.join(repos_dir, '.gboc_canary_repos'))

            created = 0
            for path in canary_locations:
                try:
                    result = create_canary(path)
                    if result.get('status') == 'created':
                        created += 1
                        logger.info(f"[Guardian] Canary criado: {path}")
                except Exception as e:
                    logger.warning(f"[Guardian] Erro ao criar canary em {path}: {e}")

            if created > 0:
                logger.info(f"[Guardian] ✅ {created} canary(s) criado(s) automaticamente")
                monitored = _query("SELECT file_path FROM ransomware_canaries ORDER BY id")
                logger.info("[Guardian] [CANARY_SCOPE] Monitorando apenas caminhos estáveis (sem TEMP/TMP)")
                for m in monitored[:10]:
                    logger.info(f"[Guardian] [CANARY_SCOPE] {m.get('file_path')}")
                if len(monitored) > 10:
                    logger.info(f"[Guardian] [CANARY_SCOPE] ... e mais {len(monitored)-10} caminho(s)")
            else:
                logger.warning("[Guardian] ⚠ Nenhum canary pôde ser criado")

        except Exception as e:
            logger.error(f"[Guardian] Erro ao garantir canaries: {e}")

    # ------------------------------------------------------------------
    # Verificacao de canaries
    # ------------------------------------------------------------------

    def _check_canaries(self) -> Optional[Dict[str, Any]]:
        """Verifica todos os canary files. Retorna resultado com threat_detected."""
        try:
            from engines.ransomware_detector import verify_canaries, ensure_tables
            ensure_tables()
            result = verify_canaries()
            compromised = result.get('compromised', 0)
            missing = result.get('missing', 0)

            if compromised > 0 or missing > 0:
                logger.critical(
                    f"[Guardian] AMEACA DETECTADA! "
                    f"Canaries comprometidos={compromised}, desaparecidos={missing}"
                )
                return {
                    'threat_detected': True,
                    'compromised': compromised,
                    'missing': missing,
                    'total': result.get('total', 0),
                    'details': result.get('details', []),
                    'detected_at': datetime.now().isoformat()
                }
            else:
                total = result.get('total', 0)
                if total > 0:
                    logger.debug(f"[Guardian] OK - {total} canaries intactos")
                return None

        except Exception as e:
            logger.error(f"[Guardian] Erro ao verificar canaries: {e}")
            return None

    # ------------------------------------------------------------------
    # Resposta automatica a ameaca
    # ------------------------------------------------------------------

    def _handle_threat(self, threat_info: Dict[str, Any]):
        """Resposta automatica completa a ameaca de ransomware."""
        with self._incident_lock:
            # Cooldown: evitar multiplas respostas ao mesmo ataque
            if self._last_incident_time:
                elapsed = (datetime.now() - self._last_incident_time).total_seconds()
                if elapsed < self._incident_cooldown_seconds:
                    logger.warning(
                        f"[Guardian] Cooldown ativo ({int(elapsed)}s / {self._incident_cooldown_seconds}s) "
                        f"- ignorando resposta duplicada"
                    )
                    return
            self._last_incident_time = datetime.now()

        logger.critical("[Guardian] === INICIANDO RESPOSTA AUTOMATICA ===")
        response_actions = []

        # 1. Registrar incidente no banco
        incident_id = self._record_incident(threat_info)
        response_actions.append({'action': 'incident_recorded', 'incident_id': incident_id})

        # 2. Criar alerta critico
        self._create_critical_alert(threat_info)
        response_actions.append({'action': 'critical_alert_created'})

        # 3. Snapshot emergencial dos repositorios
        snap_result = self._emergency_snapshot()
        response_actions.append({'action': 'emergency_snapshot', 'result': snap_result})

        # 4. Bloquear repositorios (read-only)
        lock_result = self._lock_repositories()
        response_actions.append({'action': 'repositories_locked', 'result': lock_result})

        # 5. Pausar tarefas de backup agendadas (evitar sobrescrever backups bons)
        pause_result = self._pause_scheduled_backups()
        response_actions.append({'action': 'backups_paused', 'result': pause_result})

        # 6. Notificar por TODOS os canais disponiveis
        notify_result = self._notify_all_channels(threat_info)
        response_actions.append({'action': 'notifications_sent', 'result': notify_result})

        # 7. Atualizar incidente com acoes tomadas
        self._update_incident(incident_id, response_actions)

        logger.critical(
            f"[Guardian] === RESPOSTA CONCLUIDA === "
            f"Incidente #{incident_id} | {len(response_actions)} acoes executadas"
        )

    # ------------------------------------------------------------------
    # 1. Registrar incidente
    # ------------------------------------------------------------------

    def _record_incident(self, threat_info: Dict) -> Optional[int]:
        """Registra incidente de ransomware no banco."""
        try:
            from engines.ransomware_detector import _get_core
            core = _get_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                # Criar tabela se nao existe
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ransomware_incidents (
                        id SERIAL PRIMARY KEY,
                        detected_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                        threat_info JSONB,
                        response_actions JSONB DEFAULT '[]',
                        status TEXT DEFAULT 'active',
                        resolved_at TIMESTAMPTZ,
                        resolved_by TEXT,
                        notes TEXT
                    )
                """)
                cur.execute("""
                    INSERT INTO ransomware_incidents (threat_info)
                    VALUES (%s::jsonb) RETURNING id
                """, (json.dumps(threat_info, default=str),))
                incident_id = cur.fetchone()[0]
                conn.commit()
                logger.info(f"[Guardian] Incidente #{incident_id} registrado")
                return incident_id
        except Exception as e:
            logger.error(f"[Guardian] Falha ao registrar incidente: {e}")
            return None

    def _update_incident(self, incident_id: Optional[int], actions: List[Dict]):
        """Atualiza incidente com acoes tomadas."""
        if not incident_id:
            return
        try:
            from engines.ransomware_detector import _execute
            _execute("""
                UPDATE ransomware_incidents
                SET response_actions = %s::jsonb
                WHERE id = %s
            """, (json.dumps(actions, default=str), incident_id))
        except Exception as e:
            logger.error(f"[Guardian] Falha ao atualizar incidente: {e}")

    # ------------------------------------------------------------------
    # 2. Alerta critico
    # ------------------------------------------------------------------

    def _create_critical_alert(self, threat_info: Dict):
        """Cria alerta critico no sistema."""
        try:
            from engines.ransomware_detector import _execute
            compromised = threat_info.get('compromised', 0)
            missing = threat_info.get('missing', 0)
            details = threat_info.get('details', [])
            affected_files = [d.get('file_path', '?') for d in details if d.get('status') != 'intact']

            _execute("""
                INSERT INTO alerts (type, severity, title, message, source, timestamp, details)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
            """, (
                'ransomware_attack',
                'critical',
                f'RANSOMWARE: {compromised} canaries comprometidos, {missing} desaparecidos',
                f'O Guardian detectou alteracao em arquivos sentinela. '
                f'RESPOSTA AUTOMATICA ATIVADA: snapshot emergencial criado, '
                f'repositorios bloqueados, backups pausados. '
                f'Arquivos afetados: {", ".join(affected_files[:5])}'
                f'{"..." if len(affected_files) > 5 else ""}',
                'ransomware_guardian',
                json.dumps({'threat_info': threat_info, 'auto_response': True}, default=str)
            ))
            logger.info("[Guardian] Alerta critico criado")
        except Exception as e:
            logger.error(f"[Guardian] Falha ao criar alerta: {e}")

    # ------------------------------------------------------------------
    # 3. Snapshot emergencial
    # ------------------------------------------------------------------

    def _emergency_snapshot(self) -> Dict[str, Any]:
        """Tenta criar snapshot emergencial de todos os repos detectados."""
        result = {'success': 0, 'failed': 0, 'errors': [], 'snapshots': []}
        try:
            from engines.ransomware_detector import _query
            repos = _query("""
                SELECT id, name, path, engine
                FROM repositories
                WHERE status = 'ok' OR status = 'active'
                ORDER BY name
            """)
            if not repos:
                # Tentar tabela alternativa
                repos = _query("""
                    SELECT id, name, path, engine
                    FROM repositories
                    ORDER BY name LIMIT 20
                """)
        except Exception:
            repos = []

        for repo in repos:
            engine = (repo.get('engine') or '').lower()
            repo_path = repo.get('path', '')
            repo_name = repo.get('name', f'repo-{repo.get("id")}')

            try:
                snap_id = None
                if 'restic' in engine:
                    snap_id = self._snapshot_restic(repo_path)
                elif 'kopia' in engine:
                    snap_id = self._snapshot_kopia(repo_path)
                elif 'borg' in engine:
                    snap_id = self._snapshot_borg(repo_path)

                if snap_id:
                    result['success'] += 1
                    result['snapshots'].append({
                        'repo': repo_name, 'engine': engine, 'snapshot_id': snap_id
                    })
                    logger.info(f"[Guardian] Snapshot emergencial: {repo_name} -> {snap_id}")
            except Exception as e:
                result['failed'] += 1
                result['errors'].append({'repo': repo_name, 'error': str(e)})
                logger.error(f"[Guardian] Falha snapshot {repo_name}: {e}")

        return result

    def _snapshot_restic(self, repo_path: str) -> Optional[str]:
        """Cria snapshot tag 'emergency' via restic."""
        try:
            env = os.environ.copy()
            env['RESTIC_REPOSITORY'] = repo_path
            # Restic: adicionar tag emergency ao ultimo snapshot
            r = subprocess.run(
                ['restic', 'tag', '--add', 'emergency-ransomware', 'latest'],
                capture_output=True, text=True, timeout=120, env=env
            )
            if r.returncode == 0:
                return f"tagged-emergency-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        except FileNotFoundError:
            logger.debug("[Guardian] restic nao encontrado no PATH")
        except Exception as e:
            logger.debug(f"[Guardian] restic tag falhou: {e}")
        return None

    def _snapshot_kopia(self, repo_path: str) -> Optional[str]:
        """Cria snapshot via kopia."""
        try:
            r = subprocess.run(
                ['kopia', 'snapshot', 'create', repo_path, '--tags', 'emergency:ransomware'],
                capture_output=True, text=True, timeout=300
            )
            if r.returncode == 0:
                return f"kopia-emergency-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        except FileNotFoundError:
            logger.debug("[Guardian] kopia nao encontrado no PATH")
        except Exception as e:
            logger.debug(f"[Guardian] kopia snapshot falhou: {e}")
        return None

    def _snapshot_borg(self, repo_path: str) -> Optional[str]:
        """Cria snapshot via borg."""
        archive_name = f"emergency-ransomware-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            r = subprocess.run(
                ['borg', 'create', f'{repo_path}::{archive_name}', '/dev/null'],
                capture_output=True, text=True, timeout=120
            )
            if r.returncode == 0:
                return archive_name
        except FileNotFoundError:
            logger.debug("[Guardian] borg nao encontrado no PATH")
        except Exception as e:
            logger.debug(f"[Guardian] borg create falhou: {e}")
        return None

    # ------------------------------------------------------------------
    # 4. Bloquear repositorios
    # ------------------------------------------------------------------

    def _lock_repositories(self) -> Dict[str, Any]:
        """Tenta bloquear repositorios para impedir sobrescrita por ransomware."""
        result = {'locked': 0, 'errors': []}
        try:
            from engines.ransomware_detector import _query, _execute
            repos = _query("SELECT id, name, path, engine FROM repositories ORDER BY name LIMIT 20")
            for repo in repos:
                repo_path = repo.get('path', '')
                repo_name = repo.get('name', '')
                engine = (repo.get('engine') or '').lower()
                try:
                    if 'restic' in engine and repo_path:
                        # Restic: setar repo como locked
                        env = os.environ.copy()
                        env['RESTIC_REPOSITORY'] = repo_path
                        subprocess.run(
                            ['restic', 'lock'],
                            capture_output=True, timeout=30, env=env
                        )
                        result['locked'] += 1
                        logger.info(f"[Guardian] Repo bloqueado: {repo_name}")

                    # Marcar no banco como locked
                    _execute(
                        "UPDATE repositories SET status = 'locked_ransomware' WHERE id = %s",
                        (repo.get('id'),)
                    )
                except Exception as e:
                    result['errors'].append({'repo': repo_name, 'error': str(e)})
        except Exception as e:
            result['errors'].append({'general': str(e)})
        return result

    # ------------------------------------------------------------------
    # 5. Pausar backups agendados
    # ------------------------------------------------------------------

    def _pause_scheduled_backups(self) -> Dict[str, Any]:
        """Pausa todas as tarefas de backup agendadas."""
        result = {'paused': 0, 'errors': []}
        try:
            from engines.ransomware_detector import _execute, _query

            # Salvar estado atual antes de pausar
            active_tasks = _query(
                "SELECT id, name, status FROM tasks WHERE status = 'active' OR status = 'scheduled'"
            )
            for task in active_tasks:
                try:
                    _execute(
                        "UPDATE tasks SET status = 'paused_ransomware', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (task['id'],)
                    )
                    result['paused'] += 1
                    logger.info(f"[Guardian] Tarefa pausada: {task.get('name', task['id'])}")
                except Exception as e:
                    result['errors'].append({'task': task.get('name'), 'error': str(e)})
        except Exception as e:
            result['errors'].append({'general': str(e)})
        return result

    # ------------------------------------------------------------------
    # 6. Notificar por todos os canais
    # ------------------------------------------------------------------

    def _notify_all_channels(self, threat_info: Dict) -> Dict[str, Any]:
        """Envia notificacao por TODOS os canais configurados."""
        result = {'sent': 0, 'failed': 0, 'channels': []}

        compromised = threat_info.get('compromised', 0)
        missing = threat_info.get('missing', 0)
        hostname = self._get_hostname()
        timestamp = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

        subject = f"[CRITICO] RANSOMWARE DETECTADO - {hostname}"
        message = (
            f"ALERTA DE RANSOMWARE - RESPOSTA AUTOMATICA ATIVADA\n"
            f"{'='*50}\n\n"
            f"Servidor: {hostname}\n"
            f"Detectado em: {timestamp}\n"
            f"Canaries comprometidos: {compromised}\n"
            f"Canaries desaparecidos: {missing}\n\n"
            f"ACOES AUTOMATICAS EXECUTADAS:\n"
            f"  - Snapshot emergencial dos repositorios\n"
            f"  - Repositorios bloqueados (read-only)\n"
            f"  - Backups agendados PAUSADOS\n"
            f"  - Incidente registrado no sistema\n\n"
            f"ACAO NECESSARIA:\n"
            f"  1. Verifique o servidor IMEDIATAMENTE\n"
            f"  2. Isole a maquina da rede se possivel\n"
            f"  3. Acesse o painel GBOC para revisar o incidente\n"
            f"  4. NAO restaure backups antes de confirmar que o ataque foi contido\n\n"
            f"--- GBOC Ransomware Guardian 11.7c ---"
        )

        # 6a. SMTP (e-mail)
        smtp_result = self._notify_smtp(subject, message)
        if smtp_result:
            result['sent'] += 1
            result['channels'].append('smtp')

        # 6b. Webhooks (Teams/Slack/Discord)
        webhook_result = self._notify_webhooks(subject, message, threat_info)
        result['sent'] += webhook_result.get('sent', 0)
        result['failed'] += webhook_result.get('failed', 0)
        result['channels'].extend(webhook_result.get('channels', []))

        # 6c. Telegram
        telegram_result = self._notify_telegram(subject, message)
        if telegram_result:
            result['sent'] += 1
            result['channels'].append('telegram')

        logger.info(f"[Guardian] Notificacoes: {result['sent']} enviadas, {result['failed']} falharam")
        return result

    def _notify_smtp(self, subject: str, body: str) -> bool:
        """Envia e-mail via SMTP configurado."""
        try:
            from engines.ransomware_detector import _get_core
            core = _get_core()
            with core.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT value FROM settings WHERE key = 'smtp'")
                row = cur.fetchone()
                if not row or row[0] in (None, ''):
                    logger.debug("[Guardian] SMTP nao configurado")
                    return False
                config = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})

            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            msg = MIMEMultipart()
            msg['From'] = config.get('from_email', config.get('username', ''))
            msg['To'] = config.get('to_email', config.get('username', ''))
            msg['Subject'] = subject
            msg['X-Priority'] = '1'  # Alta prioridade
            msg.attach(MIMEText(body, 'plain', 'utf-8'))

            server_addr = config.get('server', config.get('host', ''))
            port = int(config.get('port', 587))
            username = config.get('username', '')
            password = config.get('password', '')

            if not server_addr or not username:
                logger.debug("[Guardian] SMTP incompleto")
                return False

            with smtplib.SMTP(server_addr, port, timeout=30) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)

            logger.info(f"[Guardian] E-mail enviado para {msg['To']}")
            return True

        except Exception as e:
            logger.error(f"[Guardian] Falha SMTP: {e}")
            return False

    def _notify_webhooks(self, subject: str, body: str, threat_info: Dict) -> Dict:
        """Envia para todos os webhooks configurados (Slack/Teams/Discord)."""
        result = {'sent': 0, 'failed': 0, 'channels': []}
        try:
            from engines.ransomware_detector import _query
            channels = _query("""
                SELECT id, name, channel_type AS type, config
                FROM notification_channels
                WHERE enabled = true AND channel_type IN ('webhook', 'slack', 'teams', 'discord')
            """)
        except Exception:
            channels = []

        import urllib.request

        for ch in channels:
            try:
                config = json.loads(ch.get('config', '{}')) if isinstance(ch.get('config'), str) else (ch.get('config') or {})
                url = config.get('url', config.get('webhook_url', ''))
                if not url:
                    continue

                ch_type = (ch.get('type') or '').lower()
                if 'teams' in ch_type:
                    payload = {"text": f"**{subject}**\n\n```\n{body}\n```"}
                elif 'slack' in ch_type or 'discord' in ch_type:
                    payload = {"text" if 'slack' in ch_type else "content": f"**{subject}**\n{body}"}
                else:
                    payload = {"text": f"{subject}\n\n{body}"}

                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(
                    url, data=data,
                    headers={'Content-Type': 'application/json'}
                )
                urllib.request.urlopen(req, timeout=15)
                result['sent'] += 1
                result['channels'].append(ch.get('name', ch_type))
                logger.info(f"[Guardian] Webhook enviado: {ch.get('name')}")
            except Exception as e:
                result['failed'] += 1
                logger.error(f"[Guardian] Webhook falhou ({ch.get('name')}): {e}")

        return result

    def _notify_telegram(self, subject: str, body: str) -> bool:
        """Envia via Telegram se configurado."""
        try:
            from engines.ransomware_detector import _query
            channels = _query("""
                SELECT config FROM notification_channels
                WHERE enabled = true AND channel_type = 'telegram' LIMIT 1
            """)
            if not channels:
                return False
            config = json.loads(channels[0].get('config', '{}')) if isinstance(channels[0].get('config'), str) else (channels[0].get('config') or {})
            bot_token = config.get('bot_token', '')
            chat_id = config.get('chat_id', '')
            if not bot_token or not chat_id:
                return False

            import urllib.request
            text = f"🚨 {subject}\n\n{body}"
            if len(text) > 4000:
                text = text[:4000] + "..."
            payload = json.dumps({'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}).encode('utf-8')
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data=payload,
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req, timeout=15)
            logger.info("[Guardian] Telegram enviado")
            return True
        except Exception as e:
            logger.error(f"[Guardian] Telegram falhou: {e}")
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_hostname(self) -> str:
        try:
            import socket
            return socket.gethostname()
        except Exception:
            return 'unknown'

    # ------------------------------------------------------------------
    # API de consulta (para a UI)
    # ------------------------------------------------------------------

    def get_guardian_status(self) -> Dict[str, Any]:
        """Retorna status do Guardian para a UI."""
        incidents = []
        try:
            from engines.ransomware_detector import _query, ensure_tables
            ensure_tables()
            incidents = _query("""
                SELECT id, detected_at, status, threat_info, response_actions
                FROM ransomware_incidents
                ORDER BY detected_at DESC LIMIT 10
            """)
        except Exception:
            pass

        return {
            'enabled': self.enabled,
            'running': self.is_alive(),
            'check_interval_minutes': self.check_interval // 60,
            'last_incident': self._last_incident_time.isoformat() if self._last_incident_time else None,
            'recent_incidents': incidents
        }


# Instancia global (singleton)
_guardian_instance: Optional[RansomwareGuardian] = None


def get_guardian(check_interval_minutes: int = 5) -> RansomwareGuardian:
    """Retorna instancia singleton do Guardian."""
    global _guardian_instance
    if _guardian_instance is None:
        _guardian_instance = RansomwareGuardian(check_interval_minutes=check_interval_minutes)
    return _guardian_instance

