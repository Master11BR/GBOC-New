#!/usr/bin/env python3
"""
GBOC 13.2.0 - Executar Diagnóstico Completo
Script para executar todos os diagnósticos e gerar relatórios
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

# Adicionar diretório ao path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def main():
    """Executa todos os diagnósticos"""
    
    print("\n" + "=" * 80)
    print(" GBOC 13.2.0 - DIAGNÓSTICO COMPLETO DO SISTEMA")
    print("=" * 80 + "\n")
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "diagnostics": {}
    }
    
    # 1. Diagnóstico do sistema
    print("\n[1/4] Executando diagnóstico do sistema...")
    try:
        from diagnostic_report import SystemDiagnostic
        diagnostic = SystemDiagnostic()
        report = diagnostic.run_complete_diagnostic()
        results["diagnostics"]["system"] = report
        print("✓ Diagnóstico do sistema concluído")
    except Exception as e:
        print(f"✗ Erro no diagnóstico do sistema: {e}")
        results["diagnostics"]["system"] = {"error": str(e)}
    
    # 2. Unificação de versões
    print("\n[2/4] Unificando versões para 13.2.0...")
    try:
        from version_unifier import VersionUnifier
        unifier = VersionUnifier()
        success = unifier.unify_versions()
        results["diagnostics"]["version_unification"] = {
            "success": success,
            "updated_files": unifier.updated_files,
            "failed_updates": unifier.failed_updates
        }
        print("✓ Unificação de versões concluída")
    except Exception as e:
        print(f"✗ Erro na unificação de versões: {e}")
        results["diagnostics"]["version_unification"] = {"error": str(e)}
    
    # 3. Detecção de arquivos órfãos
    print("\n[3/4] Detectando arquivos órfãos...")
    try:
        from orphan_file_detector import OrphanFileDetector
        detector = OrphanFileDetector()
        orphan_report = detector.scan_system()
        results["diagnostics"]["orphan_files"] = orphan_report
        print("✓ Detecção de arquivos órfãos concluída")
    except Exception as e:
        print(f"✗ Erro na detecção de órfãos: {e}")
        results["diagnostics"]["orphan_files"] = {"error": str(e)}
    
    # 4. Diagnóstico preemptivo
    print("\n[4/4] Executando diagnóstico preemptivo...")
    try:
        from engines.preemptive_diagnostic import PreemptiveDiagnostic
        db_path = Path(__file__).parent / "data" / "gboc.db"
        
        if db_path.exists():
            preemptive = PreemptiveDiagnostic(str(db_path))
            preemptive_report = preemptive.run_preemptive_check()
            results["diagnostics"]["preemptive"] = preemptive_report
            print("✓ Diagnóstico preemptivo concluído")
        else:
            print("⚠ Database não encontrado - pulando diagnóstico preemptivo")
            results["diagnostics"]["preemptive"] = {"skipped": "Database not found"}
    except Exception as e:
        print(f"✗ Erro no diagnóstico preemptivo: {e}")
        results["diagnostics"]["preemptive"] = {"error": str(e)}
    
    # Salvar relatório consolidado
    print("\n[FINAL] Salvando relatório consolidado...")
    try:
        logs_dir = Path(__file__).parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        
        report_file = logs_dir / f"complete_diagnostic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        import json
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Relatório consolidado salvo em: {report_file}")
    except Exception as e:
        print(f"✗ Erro ao salvar relatório: {e}")
    
    # Imprimir resumo final
    print("\n" + "=" * 80)
    print(" RESUMO GERAL")
    print("=" * 80)
    
    # Contar issues e warnings
    total_issues = 0
    total_warnings = 0
    
    if "system" in results["diagnostics"]:
        sys_diag = results["diagnostics"]["system"]
        if isinstance(sys_diag, dict):
            total_issues += len(sys_diag.get("issues", []))
            total_warnings += len(sys_diag.get("warnings", []))
    
    if "preemptive" in results["diagnostics"]:
        preempt = results["diagnostics"]["preemptive"]
        if isinstance(preempt, dict):
            total_issues += len(preempt.get("alerts", []))
            total_warnings += len(preempt.get("warnings", []))
    
    print(f"\n✓ Sistema diagnosticado: GBOC 13.2.0")
    print(f"✓ Issues críticos encontrados: {total_issues}")
    print(f"✓ Warnings encontrados: {total_warnings}")
    
    if "orphan_files" in results["diagnostics"]:
        orphans = results["diagnostics"]["orphan_files"]
        if isinstance(orphans, dict):
            print(f"✓ Arquivos órfãos detectados: {orphans.get('orphan_files', 0)}")
    
    if "version_unification" in results["diagnostics"]:
        version = results["diagnostics"]["version_unification"]
        if isinstance(version, dict) and version.get("success"):
            print(f"✓ Versões unificadas com sucesso")
    
    print("\n" + "=" * 80)
    
    if total_issues > 0:
        print("\n⚠️  ATENÇÃO: Issues críticos foram encontrados!")
        print("   Verifique o relatório completo para detalhes.")
        return 1
    else:
        print("\n✓ Sistema saudável - Nenhum issue crítico encontrado")
        return 0

if __name__ == "__main__":
    sys.exit(main())

