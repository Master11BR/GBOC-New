# Copilot Instructions

## Diretrizes de projeto
- Faça somente mudanças mínimas e localizadas, focadas em resolver o problema descrito.
- Não refatore, não reorganize e não “melhore” partes que já estão funcionando e foram validadas, mesmo que você veja oportunidades.
- Não altere a API pública (assinaturas de funções, tipos, contratos, nomes públicos) nem o comportamento de funcionalidades que não estejam diretamente relacionadas ao erro relatado.
- Não modifique arquivos ou módulos que não forem citados explicitamente na tarefa; ao corrigir problemas, limite mudanças ao escopo solicitado (por exemplo, mexa somente em assuntos do Kopia) e não altere módulos que já estão funcionando.
- Se identificar melhorias maiores ou refatorações úteis, apenas descreva em texto como sugestão, sem aplicar essas mudanças no código agora

## Regras específicas do projeto
### Ransomware Guardian
- Não monitorar a pasta temporária pelo canary do Ransomware Guardian para evitar falsos positivos.