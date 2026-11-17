# Fine-tuning do diagnóstico do GBOC

O GBOC **não treina modelos dentro do Agente** (servidor de backup normalmente não tem GPU). O fluxo é:

1. **Gerar dataset no Agente** — tela *IA: Conhecimento, MCP e Treino* → aba *Fine-tuning* → **Gerar dataset**.
   - Só entram casos **reais** de diagnóstico do próprio ambiente:
     - *Validados*: o operador marcou "Resolveu" (recomendado);
     - *Validados + recuperados*: inclui casos sem avaliação cuja tarefa voltou a concluir com sucesso depois do diagnóstico.
   - Saída: `data/ai/finetune/gboc_diag_<data>.train.jsonl` (+ `.val.jsonl` com 20+ exemplos) e um manifesto.
   - Recomendado: **30+ exemplos** antes de treinar.
2. **Treinar numa máquina com GPU NVIDIA** — copie o `.jsonl` e rode:
   ```
   pip install unsloth trl datasets
   python train_lora_gboc.py --train gboc_diag_XXXX.train.jsonl --val gboc_diag_XXXX.val.jsonl --export-gguf
   ```
   Modelo base padrão: `unsloth/Qwen2.5-3B-Instruct-bnb-4bit` (8 GB de VRAM). Para 7B/8B use 16 GB+.
3. **Importar no Ollama pelo Agente** — aba *Fine-tuning* → **Importar no Ollama**:
   - *Modelo completo (.gguf)*: caminho do arquivo gerado em `saida/gguf/`;
   - *Adapter LoRA*: arquivo do adapter + modelo base já instalado no Ollama (mesma família/tamanho do treino).
   - Marque **Usar no diagnóstico** para o Agente passar a usar o modelo treinado.

O RAG continua ativo junto com o modelo treinado: o fine-tuning ensina o *formato e o estilo* do diagnóstico do seu
ambiente; o RAG traz os *fatos atuais* (falhas, execuções, soluções validadas mais recentes).
