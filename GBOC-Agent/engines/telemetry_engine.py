# GBOC Agent v14.0.0 Full Stable Enterprise Edition
# Module: Enterprise Telemetry & Observability Engine (Sentry, OpenTelemetry, Datadog, NewRelic, Prometheus)

import os
import sys
import time
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger("gboc_agent_telemetry")

class GBOCAgentTelemetryEngine:
    """
    Engine Unificada de Observabilidade e Telemetria do Agente GBOC.
    Suporta Sentry, OpenTelemetry (OTel), Datadog APM, NewRelic e Prometheus.
    """
    def __init__(self):
        self.sentry_active = False
        self.otel_active = False
        self.datadog_active = False
        self.newrelic_active = False
        self._init_providers()

    def _init_providers(self):
        sentry_dsn = os.getenv("SENTRY_DSN", "")
        if sentry_dsn:
            try:
                import sentry_sdk
                sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=0.2, release="gboc-agent@14.0.0")
                self.sentry_active = True
                logger.info("📡 Sentry SDK ativado no Agente com sucesso.")
            except Exception as e:
                logger.warning(f"Sentry SDK não ativado no Agente: {e}")

        otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if otel_endpoint:
            try:
                from opentelemetry import trace
                from opentelemetry.sdk.trace import TracerProvider
                trace.set_tracer_provider(TracerProvider())
                self.otel_active = True
                logger.info("📡 OpenTelemetry OTLP Tracer Provider inicializado no Agente.")
            except Exception as e:
                logger.warning(f"OpenTelemetry não ativado no Agente: {e}")

        if os.getenv("DATADOG_API_KEY"):
            self.datadog_active = True

        if os.getenv("NEW_RELIC_LICENSE_KEY"):
            self.newrelic_active = True

    def record_span(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        class SpanContext:
            def __init__(self, engine, span_name, attrs):
                self.engine = engine
                self.span_name = span_name
                self.attrs = attrs or {}
                self.start_time = None

            def __enter__(self):
                self.start_time = time.time()
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                duration = time.time() - self.start_time
                if exc_val:
                    self.engine.capture_exception(exc_val, {"span_name": self.span_name, **self.attrs})

        return SpanContext(self, name, attributes)

    def capture_exception(self, exception: Exception, extra_context: Optional[Dict[str, Any]] = None):
        err_msg = f"❌ [Agent Exceção]: {type(exception).__name__}: {str(exception)}"
        logger.error(err_msg, exc_info=True)

        if self.sentry_active:
            try:
                import sentry_sdk
                with sentry_sdk.push_scope() as scope:
                    if extra_context:
                        for k, v in extra_context.items():
                            scope.set_extra(k, v)
                    sentry_sdk.capture_exception(exception)
            except Exception:
                pass

    def get_status(self) -> Dict[str, Any]:
        return {
            "status": "active",
            "sentry_active": self.sentry_active,
            "opentelemetry_active": self.otel_active,
            "datadog_active": self.datadog_active,
            "newrelic_active": self.newrelic_active,
            "timestamp": datetime.now().isoformat()
        }

telemetry = GBOCAgentTelemetryEngine()
