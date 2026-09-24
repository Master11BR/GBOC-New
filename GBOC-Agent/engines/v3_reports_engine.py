#!/usr/bin/env python3
"""
GBOC System v14.7.0 Enterprise Edition
Module: Reports Engine Compatibility Layer (v3 -> v4)
Exposes all Master Report Standard v4.0 functions and schemas with full backward compatibility.
"""

from engines.v4_reports_engine import (
    generate_real_report_data_v4,
    _clean_task_name,
    _sla_badge,
    _compute_integrity_hash,
    get_process_uptime,
    predict_exhaustion,
    build_ai_recommendation,
    collect_backup_summary,
    collect_sla_per_task,
    collect_engine_stats,
    collect_daily_series,
    collect_retention_policy,
    collect_ransomware_status,
    collect_unprotected_volumes,
    detect_anomalies,
    collect_health_timeline,
    collect_engine_health,
    collect_config_drift,
    compare_periods,
    FLAGSHIPS_CATALOG_8,
    FLAGSHIPS_CATALOG_7,
    NEW_REPORTS_CATALOG_5,
)

# Aliases retrocompatíveis
get_real_uptime = get_process_uptime
predict_storage_exhaustion = predict_exhaustion

def generate_real_report_data_v3(rep_id: int, catalog_50: list = None) -> dict:
    """Delegador compatível para o Master Report Engine v4.0."""
    return generate_real_report_data_v4(rep_id, catalog_50=catalog_50)
