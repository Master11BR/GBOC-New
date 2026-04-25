#!/usr/bin/env python3
"""
GBOC Agent v8 - Engine Validator
Valida a instalação e conectividade dos motores de backup (Restic, Kopia, Duplicati)
"""

import subprocess
import os
import logging
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class EngineValidator:
    """Validador de motores de backup"""

    def __init__(self):
        self.engines = {
            'restic': {
                'name': 'Restic',
                'commands': ['restic', 'version'],
                'test_command': ['restic', 'version'],
                'description': 'Restic - Backup moderno e seguro'
            },
            'kopia': {
                'name': 'Kopia',
                'commands': ['kopia', '--version'],
                'test_command': ['kopia', '--version'],
                'description': 'Kopia - Backup rápido e eficiente'
            },
            'duplicati': {
                'name': 'Duplicati',
                'commands': ['duplicati-cli', 'help'],
                'test_command': ['duplicati-cli', 'help'],
                'paths': [
                    'duplicati-cli.exe',
                    'C:\\Program Files\\Duplicati 2\\Duplicati.CommandLine.exe',
                    'C:\\Program Files (x86)\\Duplicati 2\\Duplicati.CommandLine.exe'
                ],
                'description': 'Duplicati - Backup com interface web'
            },
            'gboc_native': {
                'name': 'GBOC Native',
                'description': 'Motor de backup nativo e proprietário',
                'is_native': True
            }
        }

    def validate_all_engines(self) -> Dict[str, Dict]:
        """
        Valida todos os motores instalados
        Retorna status detalhado de cada motor
        """
        results = {}

        for engine_name, engine_config in self.engines.items():
            results[engine_name] = self.validate_engine(engine_name)

        return results

    def validate_engine(self, engine_name: str) -> Dict:
        """
        Valida um motor específico
        """
        if engine_name not in self.engines:
            return {
                'installed': False,
                'available': False,
                'error': f'Motor {engine_name} não suportado',
                'version': None
            }

        config = self.engines[engine_name]
        
        # Lógica especial para o motor nativo
        if config.get('is_native'):
            try:
                from native_engine.engine import GBOCNativeEngine
                return {
                    'name': config['name'],
                    'description': config['description'],
                    'installed': True,
                    'available': True,
                    'version': '1.0.0', # Versão interna
                    'error': None,
                    'path': 'N/A (Nativo)'
                }
            except ImportError as e:
                return {
                    'name': config['name'],
                    'description': config['description'],
                    'installed': False,
                    'available': False,
                    'version': None,
                    'error': f'Falha ao importar motor nativo: {e}',
                    'path': None
                }

        result = {
            'name': config['name'],
            'description': config['description'],
            'installed': False,
            'available': False,
            'version': None,
            'error': None,
            'path': None
        }

        try:
            # Verificar instalação
            executable_path = self._find_executable(engine_name)
            if not executable_path:
                result['error'] = f'Executável não encontrado para {config["name"]}'
                return result

            result['installed'] = True
            result['path'] = executable_path

            # Testar funcionalidade básica
            test_result = self._test_engine_functionality(engine_name, executable_path)
            result.update(test_result)

        except Exception as e:
            result['error'] = f'Erro ao validar {config["name"]}: {str(e)}'
            logger.error(f'Erro na validação do motor {engine_name}: {e}')

        return result

    def _find_executable(self, engine_name: str) -> Optional[str]:
        """
        Encontra o executável do motor no PATH ou caminhos específicos
        """
        config = self.engines[engine_name]

        # Primeiro tentar no PATH
        try:
            if engine_name == 'duplicati':
                # Para Duplicati, tentar múltiplos caminhos
                for path in config.get('paths', []):
                    if os.path.exists(path):
                        return path
                # Tentar encontrar via which/shutil.which
                executable = shutil.which('duplicati-cli')
                if executable:
                    return executable
            else:
                # Para outros motores, usar shutil.which
                import shutil
                executable = shutil.which(config['commands'][0])
                if executable:
                    return executable
        except:
            pass

        # Se não encontrou, tentar executar diretamente (pode estar no PATH)
        try:
            result = subprocess.run(
                config['commands'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return config['commands'][0]  # Assume que está no PATH
        except:
            pass

        return None

    def _test_engine_functionality(self, engine_name: str, executable_path: str) -> Dict:
        """
        Testa a funcionalidade básica do motor
        """
        config = self.engines[engine_name]

        try:
            # Executar comando de teste
            cmd = config['test_command'].copy()
            if engine_name == 'duplicati' and not executable_path.endswith('.exe'):
                cmd[0] = executable_path

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=os.environ.copy()
            )

            if result.returncode == 0:
                # Extrair versão se possível
                version = self._extract_version(engine_name, result.stdout, result.stderr)
                return {
                    'available': True,
                    'version': version,
                    'error': None
                }
            else:
                return {
                    'available': False,
                    'version': None,
                    'error': f'Comando falhou: {result.stderr.strip()}'
                }

        except subprocess.TimeoutExpired:
            return {
                'available': False,
                'version': None,
                'error': 'Timeout: Motor não respondeu dentro do tempo limite'
            }
        except Exception as e:
            return {
                'available': False,
                'version': None,
                'error': f'Erro ao testar funcionalidade: {str(e)}'
            }

    def _extract_version(self, engine_name: str, stdout: str, stderr: str) -> Optional[str]:
        """
        Extrai a versão do output do motor
        """
        output = stdout + stderr

        if engine_name == 'restic':
            # Restic mostra versão na primeira linha
            lines = output.strip().split('\n')
            if lines and 'restic' in lines[0].lower():
                return lines[0].strip()

        elif engine_name == 'kopia':
            # Kopia mostra versão
            lines = output.strip().split('\n')
            for line in lines:
                if 'kopia' in line.lower() and ('version' in line.lower() or any(c.isdigit() for c in line)):
                    return line.strip()

        elif engine_name == 'duplicati':
            # Duplicati pode mostrar versão no help
            lines = output.strip().split('\n')
            for line in lines:
                if 'version' in line.lower() or any(c.isdigit() for c in line):
                    return line.strip()

        return None

    def test_repository_connection(self, repo_data: Dict) -> Dict:
        """
        Testa a conexão com um repositório específico
        """
        engine = repo_data.get('engine', 'restic')
        repo_type = repo_data.get('type', 'local')

        result = {
            'engine': engine,
            'repo_type': repo_type,
            'connection_tested': False,
            'connection_ok': False,
            'error': None,
            'details': {}
        }

        # Primeiro verificar se o motor está disponível
        engine_status = self.validate_engine(engine)
        if not engine_status['available']:
            result['error'] = f'Motor {engine} não está disponível: {engine_status["error"]}'
            return result

        try:
            result['connection_tested'] = True

            if engine == 'restic':
                result.update(self._test_restic_connection(repo_data))
            elif engine == 'kopia':
                result.update(self._test_kopia_connection(repo_data))
            elif engine == 'duplicati':
                result.update(self._test_duplicati_connection(repo_data))
            else:
                result['error'] = f'Motor {engine} não suportado para teste de conexão'

        except Exception as e:
            result['error'] = f'Erro ao testar conexão: {str(e)}'

        return result

    def _test_restic_connection(self, repo_data: Dict) -> Dict:
        """Testa conexão Restic (versão simplificada)"""
        try:
            env = os.environ.copy()
            repo_type = (repo_data.get('repo_type') or repo_data.get('type') or 'local').lower()
            env['RESTIC_PASSWORD'] = repo_data.get('motor_password') if repo_type == 'local' else repo_data.get('cloud_password', '')

            # Configurar repositório baseado no tipo
            if repo_data.get('type') == 'local':
                env['RESTIC_REPOSITORY'] = repo_data.get('path', '')
            else:
                # Para nuvem, usar bucket como teste básico
                env['RESTIC_REPOSITORY'] = repo_data.get('bucket', '')

            # Tentar comando version (mais rápido que snapshots)
            result = subprocess.run(
                ['restic', 'version'],
                env=env,
                capture_output=True,
                text=True,
                timeout=10
            )

            return {
                'connection_ok': result.returncode == 0,
                'error': result.stderr.strip() if result.returncode != 0 else None,
                'details': {'command': 'version', 'exit_code': result.returncode}
            }

        except Exception as e:
            return {
                'connection_ok': False,
                'error': str(e),
                'details': {}
            }

    def _test_kopia_connection(self, repo_data: Dict) -> Dict:
        """Testa conexão Kopia (versão simplificada)"""
        try:
            # Tentar comando version
            result = subprocess.run(
                ['kopia', '--version'],
                capture_output=True,
                text=True,
                timeout=10
            )

            return {
                'connection_ok': result.returncode == 0,
                'error': result.stderr.strip() if result.returncode != 0 else None,
                'details': {'command': 'version', 'exit_code': result.returncode}
            }

        except Exception as e:
            return {
                'connection_ok': False,
                'error': str(e),
                'details': {}
            }

    def _test_duplicati_connection(self, repo_data: Dict) -> Dict:
        """Testa conexão Duplicati (versão simplificada)"""
        try:
            # Encontrar executável
            executable = self._find_executable('duplicati')
            if not executable:
                return {
                    'connection_ok': False,
                    'error': 'Duplicati CLI não encontrado',
                    'details': {}
                }

            # Tentar comando help
            result = subprocess.run(
                [executable, 'help'],
                capture_output=True,
                text=True,
                timeout=15
            )

            return {
                'connection_ok': result.returncode == 0,
                'error': result.stderr.strip() if result.returncode != 0 else None,
                'details': {'command': 'help', 'exit_code': result.returncode}
            }

        except Exception as e:
            return {
                'connection_ok': False,
                'error': str(e),
                'details': {}
            }

    def get_validation_report(self) -> str:
        """
        Gera relatório completo de validação
        """
        results = self.validate_all_engines()

        report = []
        report.append("=== RELATÓRIO DE VALIDAÇÃO DOS MOTORES ===\n")

        all_ok = True
        for engine_name, status in results.items():
            report.append(f"🔧 {status['name']}")
            report.append(f"   Descrição: {status['description']}")

            if status['installed']:
                report.append("   ✅ Instalado")
                report.append(f"   📁 Caminho: {status['path']}")
                if status['available']:
                    report.append("   ✅ Funcional")
                    if status['version']:
                        report.append(f"   📋 Versão: {status['version']}")
                else:
                    report.append("   ❌ Problema de funcionalidade")
                    report.append(f"   ⚠️  Erro: {status['error']}")
                    all_ok = False
            else:
                report.append("   ❌ Não instalado")
                report.append(f"   ⚠️  Erro: {status['error']}")
                all_ok = False

            report.append("")

        if all_ok:
            report.append("🎉 Todos os motores estão OK!")
        else:
            report.append("⚠️  Alguns motores têm problemas. Verifique a instalação.")

        return "\n".join(report)


def validate_engines_cli():
    """Função CLI para validar motores"""
    validator = EngineValidator()
    report = validator.get_validation_report()
    print(report)


def validate_repository_cli(repo_data):
    """Função CLI para validar repositório"""
    validator = EngineValidator()
    result = validator.test_repository_connection(repo_data)

    print(f"=== TESTE DE CONEXÃO DO REPOSITÓRIO ===")
    print(f"Engine: {result['engine']}")
    print(f"Tipo: {result['repo_type']}")

    if result['connection_tested']:
        if result['connection_ok']:
            print("✅ Conexão OK")
        else:
            print("❌ Conexão falhou")
            print(f"Erro: {result['error']}")
    else:
        print("❌ Teste não realizado")
        print(f"Erro: {result['error']}")


if __name__ == "__main__":
    validate_engines_cli()
