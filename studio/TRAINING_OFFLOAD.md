# Offload dei layer nel training (Ganjalf)

In Ganjalf l'opzione **Offload layers** del training parte su **Auto**:

- se il modello, con il batch e il rank scelti, entra nella VRAM, non si sposta niente e il training gira tutto sulla GPU;
- se non entra, i layer del decoder che avanzano restano nella RAM di sistema (memoria *pinned*) e vengono copiati sulla GPU poco prima di essere usati. Il calcolo resta sempre sulla GPU: la RAM fa da magazzino.

Si appoggia a BlockSwap di Unsloth (`offload_layers = "auto"` in `from_pretrained` e `get_peft_model`). Insieme lavorano gli altri due risparmi già attivi: il gradient checkpointing `unsloth`, che tiene le activation in RAM, e gli ottimizzatori `paged_adamw_*`.

## Quando non si applica

L'interfaccia manda `0` per il full fine-tuning (lì servirebbe FSDP2 con CPU offload, che Studio non usa), con il gradient checkpointing spento e su Mac/MLX o GPU a memoria unificata (APU, DGX Spark). Via API, una richiesta con offload e checkpointing spento viene rifiutata.

Al caricamento, Auto ricade su `0` da solo, con una riga nel log, anche in questi casi:

- nessuna GPU CUDA o ROCm;
- caricamento a 8 bit, checkpoint GGUF, `fast_inference` (GRPO con vLLM), teste di classificazione;
- training distribuito che già divide i pesi tra le GPU.

Per i modelli **MoE** (es. Qwen3.6-35B-A3B) l'offload copia tutti gli esperti anche se ne calcola pochi: i passi diventano limitati dalla PCIe. Su questi conviene prima ridurre `max_seq_length` o il batch.

L'API compatibile OpenAI (`/v1/fine_tuning`) mantiene il default `0`, perché solo così i job vengono raggruppati in un unico training multi-LoRA.

## Quanto costa sulla tua macchina

```bash
# installazione col launcher
~/.ganjalf-studio/unsloth_studio/bin/python scripts/ganjalf-offload-bench.py \
    --model unsloth/Qwen3.6-27B --budgets full,16,12 --seq-len 2048

# Docker
docker exec -it <container> /opt/unsloth-studio/unsloth_studio/bin/python \
    /opt/unsloth-studio/src/scripts/ganjalf-offload-bench.py --model unsloth/Qwen3.6-27B --budgets full,16,12
```

Ogni budget gira in un processo separato e limita la VRAM come il campo *VRAM budget* dell'interfaccia. La tabella finale riporta tempo per passo, quanti layer sono finiti in RAM, GiB copiati per passo e `stall ms/step`, cioè il tempo in cui la GPU ha aspettato la PCIe: vicino a 0 vuol dire che le copie erano nascoste dietro al calcolo. Usa un checkpoint safetensors (non GGUF) e lascia la GPU libera da altri lavori mentre gira.
