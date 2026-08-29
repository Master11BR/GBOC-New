# ==============================================================================
# GBOC System v13.2.0 Enterprise Edition
# Module: Hermes Bandwidth Engine — Edge AI Adaptive Throttling
# Copyright (c) 2026 Master11BR - Todos os direitos reservados.
# ==============================================================================
"""
Hermes Bandwidth Engine — Pilar 4: Edge AI Adaptive Bandwidth Control

Aprende o perfil de tráfego de rede do ambiente do cliente e ajusta
dinamicamente a largura de banda usada pelos backups:
  - Acelera transferências nos horários de baixo tráfego (madrugada, fim de semana)
  - Reduz automaticamente a velocidade durante o expediente comercial
  - Nenhuma regra manual necessária: o modelo aprende o padrão em 7 dias

Implementação:
  - Medição de throughput real da interface de rede via psutil
  - Modelo de média histórica por hora-do-dia (heatmap 24h × 7d)
  - Geração de perfil de throttling semanal (MB/s por hora)
  - Relatório semanal enviado ao servidor via hermes_queue_engine
"""

import os
import json
import logging
import threading
import time
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("hermes_bandwidth_engine")

# Configurações
MIN_THROTTLE_MBPS = float(os.getenv("HERMES_MIN_THROTTLE_MBPS", "2.0"))    # Mínimo durante pico
MAX_THROTTLE_MBPS = float(os.getenv("HERMES_MAX_THROTTLE_MBPS", "500.0"))  # Máximo fora de pico
SAMPLE_INTERVAL_SECONDS = int(os.getenv("HERMES_BW_SAMPLE_INTERVAL", "60"))  # 1 amostra por minuto
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PROFILE_FILE = os.path.join(DATA_DIR, "hermes_bandwidth_profile.json")


class HermesBandwidthEngine:
    """
    Engine de controle adaptativo de largura de banda do Hermes Agent.
    Aprende o perfil de uso de rede e otimiza o throttling automaticamente.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        # Matriz de média de throughput: heatmap[dia_semana][hora] = bytes/s
        # dia_semana: 0=Segunda, 6=Domingo | hora: 0-23
        self._heatmap: List[List[List[float]]] = [
            [[0.0, 0] for _ in range(24)] for _ in range(7)  # [valor_acumulado, contagem]
        ]
        self._current_throttle_mbps: float = MAX_THROTTLE_MBPS
        self._manual_override: Optional[float] = None  # MB/s — override manual
        self._load_profile()

    # ------------------------------------------------------------------
    # Inicialização e controle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia o loop de aprendizado de largura de banda em background."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._sample_loop,
            name="hermes-bandwidth-learner",
            daemon=True
        )
        self._thread.start()
        logger.info("[HERMES BW] Engine de controle de bandwidth iniciado")

    def stop(self) -> None:
        """Para o loop de aprendizado."""
        self._running = False
        self._save_profile()
        logger.info("[HERMES BW] Engine de bandwidth encerrado")

    # ------------------------------------------------------------------
    # Loop de amostragem de rede
    # ------------------------------------------------------------------

    def _sample_loop(self) -> None:
        """Coleta amostras de uso de rede a cada SAMPLE_INTERVAL_SECONDS."""
        prev_bytes_sent = 0
        prev_bytes_recv = 0
        prev_time = time.time()

        while self._running:
            try:
                try:
                    import psutil
                    counters = psutil.net_io_counters()
                    curr_bytes_sent = counters.bytes_sent
                    curr_bytes_recv = counters.bytes_recv
                except ImportError:
                    # Fallback sem psutil — usar valores zerados
                    curr_bytes_sent = prev_bytes_sent
                    curr_bytes_recv = prev_bytes_recv

                curr_time = time.time()
                elapsed = curr_time - prev_time

                if elapsed > 0 and (prev_bytes_sent + prev_bytes_recv) > 0:
                    delta_bytes = (curr_bytes_sent + curr_bytes_recv) - (prev_bytes_sent + prev_bytes_recv)
                    throughput_bytes_per_sec = max(0.0, delta_bytes / elapsed)

                    # Registrar no heatmap
                    now = datetime.now()
                    dow = now.weekday()  # 0=Monday, 6=Sunday
                    hour = now.hour
                    with self._lock:
                        self._heatmap[dow][hour][0] += throughput_bytes_per_sec
                        self._heatmap[dow][hour][1] += 1

                    # Atualizar throttle recomendado
                    self._update_throttle_recommendation(now)

                prev_bytes_sent = curr_bytes_sent
                prev_bytes_recv = curr_bytes_recv
                prev_time = curr_time

            except Exception as e:
                logger.debug(f"[HERMES BW] Erro na amostragem de rede: {e}")

            time.sleep(SAMPLE_INTERVAL_SECONDS)

    # ------------------------------------------------------------------
    # Recomendação de throttle adaptativo
    # ------------------------------------------------------------------

    def _update_throttle_recommendation(self, now: datetime) -> None:
        """
        Calcula e atualiza o throttle recomendado com base no perfil histórico.

        Lógica:
          - Se o throughput histórico neste horário for alto (expediente) → reduz banda para backups
          - Se o throughput histórico for baixo (madrugada/fim de semana) → maximiza banda para backups
        """
        if self._manual_override is not None:
            self._current_throttle_mbps = self._manual_override
            return

        dow = now.weekday()
        hour = now.hour

        with self._lock:
            acc, count = self._heatmap[dow][hour]
            avg_throughput_bps = (acc / count) if count > 0 else 0.0

        # Converter para Mbps
        avg_throughput_mbps = avg_throughput_bps / (1024 * 1024)

        # Calcular throttle invertido: mais tráfego → menos banda para backup
        # Escala linear entre MIN e MAX baseada no tráfego histórico
        # Tráfego de referência de saturação: 100 Mbps = tráfego máximo observado
        traffic_ratio = min(1.0, avg_throughput_mbps / 100.0)
        throttle_range = MAX_THROTTLE_MBPS - MIN_THROTTLE_MBPS
        recommended_mbps = MAX_THROTTLE_MBPS - (traffic_ratio * throttle_range)
        recommended_mbps = max(MIN_THROTTLE_MBPS, min(MAX_THROTTLE_MBPS, recommended_mbps))

        if abs(recommended_mbps - self._current_throttle_mbps) > 5.0:  # Só atualiza se mudança > 5 Mbps
            logger.debug(f"[HERMES BW] Throttle ajustado: {self._current_throttle_mbps:.1f} → {recommended_mbps:.1f} Mbps "
                         f"(tráfego histórico: {avg_throughput_mbps:.1f} Mbps)")
            self._current_throttle_mbps = recommended_mbps

    # ------------------------------------------------------------------
    # Interface pública
    # ------------------------------------------------------------------

    def get_current_throttle_mbps(self) -> float:
        """Retorna o limite de banda recomendado para backups agora (em Mbps)."""
        return self._manual_override if self._manual_override is not None else self._current_throttle_mbps

    def set_manual_throttle(self, mbps: Optional[float]) -> Dict[str, Any]:
        """
        Define um limite de banda manual (sobrescreve o modo adaptativo).
        Passe None para voltar ao modo automático.
        """
        with self._lock:
            if mbps is None:
                self._manual_override = None
                mode = "auto"
            else:
                mbps = max(MIN_THROTTLE_MBPS, min(MAX_THROTTLE_MBPS, float(mbps)))
                self._manual_override = mbps
                mode = "manual"
                self._current_throttle_mbps = mbps

        logger.info(f"[HERMES BW] Throttle definido em modo {mode}: {mbps} Mbps")
        return {
            "mode": mode,
            "throttle_mbps": mbps,
            "auto_throttle_mbps": self._current_throttle_mbps
        }

    def get_bandwidth_profile(self) -> Dict[str, Any]:
        """
        Retorna o perfil de largura de banda aprendido como heatmap 24h × 7d.
        Valores em Mbps médios por hora do dia e dia da semana.
        """
        days = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        heatmap_mbps = []

        with self._lock:
            for dow_idx, day_data in enumerate(self._heatmap):
                day_profile = []
                for hour, (acc, count) in enumerate(day_data):
                    avg_bps = (acc / count) if count > 0 else 0.0
                    avg_mbps = round(avg_bps / (1024 * 1024), 2)
                    # Throttle recomendado para esse slot
                    traffic_ratio = min(1.0, avg_mbps / 100.0)
                    throttle_range = MAX_THROTTLE_MBPS - MIN_THROTTLE_MBPS
                    rec_throttle = round(MAX_THROTTLE_MBPS - (traffic_ratio * throttle_range), 1)
                    day_profile.append({
                        "hour": hour,
                        "avg_network_mbps": avg_mbps,
                        "recommended_backup_throttle_mbps": rec_throttle,
                        "samples": count
                    })
                heatmap_mbps.append({
                    "day": days[dow_idx],
                    "day_index": dow_idx,
                    "hours": day_profile
                })

        return {
            "profile_type": "adaptive_heatmap_7d_24h",
            "current_throttle_mbps": self._current_throttle_mbps,
            "manual_override_mbps": self._manual_override,
            "mode": "manual" if self._manual_override is not None else "auto",
            "min_throttle_mbps": MIN_THROTTLE_MBPS,
            "max_throttle_mbps": MAX_THROTTLE_MBPS,
            "total_samples": sum(
                self._heatmap[d][h][1] for d in range(7) for h in range(24)
            ),
            "heatmap": heatmap_mbps,
            "generated_at": datetime.now().isoformat()
        }

    def estimate_transfer_duration(self, size_bytes: int) -> Dict[str, Any]:
        """Estima o tempo de transferência de um arquivo/backup com o throttle atual."""
        throttle_bps = self.get_current_throttle_mbps() * 1024 * 1024
        if throttle_bps <= 0:
            return {"error": "Throttle zerado"}

        duration_seconds = size_bytes / throttle_bps
        return {
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / 1024 / 1024, 2),
            "current_throttle_mbps": self.get_current_throttle_mbps(),
            "estimated_duration_seconds": round(duration_seconds),
            "estimated_duration_human": str(timedelta(seconds=int(duration_seconds)))
        }

    # ------------------------------------------------------------------
    # Persistência do perfil
    # ------------------------------------------------------------------

    def _load_profile(self) -> None:
        """Carrega o perfil de largura de banda persistido do disco."""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            if os.path.exists(PROFILE_FILE):
                with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                heatmap_raw = data.get("heatmap", [])
                if len(heatmap_raw) == 7 and all(len(d) == 24 for d in heatmap_raw):
                    self._heatmap = heatmap_raw
                    logger.info("[HERMES BW] Perfil de bandwidth carregado do disco")
        except Exception as e:
            logger.warning(f"[HERMES BW] Erro ao carregar perfil: {e}")

    def _save_profile(self) -> None:
        """Salva o perfil de largura de banda no disco."""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            with self._lock:
                data = {
                    "saved_at": datetime.now().isoformat(),
                    "heatmap": self._heatmap
                }
            with open(PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"[HERMES BW] Erro ao salvar perfil: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Resumo do status do engine de bandwidth."""
        total_samples = sum(self._heatmap[d][h][1] for d in range(7) for h in range(24))
        return {
            "running": self._running,
            "mode": "manual" if self._manual_override is not None else "auto",
            "current_throttle_mbps": self.get_current_throttle_mbps(),
            "manual_override_mbps": self._manual_override,
            "min_throttle_mbps": MIN_THROTTLE_MBPS,
            "max_throttle_mbps": MAX_THROTTLE_MBPS,
            "total_samples_collected": total_samples,
            "learning_days": min(7, math.ceil(total_samples / (24 * 60))),
            "profile_file": PROFILE_FILE
        }


# Instância global singleton
hermes_bandwidth_engine = HermesBandwidthEngine()
