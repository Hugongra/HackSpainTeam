# HackSpainTeam

Repositorio del equipo HackSpain '26 · HappyRobot track.

| Folder | What |
|---|---|
| [`knowledge/`](knowledge/README.md) | Shared, published research — start with the index and read 01→07 |
| [`angryrobots/`](angryrobots/README.md) | **Project base (AngryRobots)** — our fork of [getphoneflow/phoneflow](https://github.com/getphoneflow/phoneflow) (git subtree, `git subtree pull --prefix=angryrobots https://github.com/getphoneflow/phoneflow main --squash` to update). Frontend deploys to GitHub Pages via `.github/workflows/pages.yml` |
| [`insights/`](insights/README.md) | Personal work folders (one per person); promote to `knowledge/` when it becomes team truth |
| [`hr_watch.py`](hr_watch.py) | All-layers HappyRobot watcher (`whoami`, `map`, `poll`, `stream`, `listen`, `realtime`, `sql`, `get`) — needs `HR_API_KEY` |
| [`ar_pipeline_ui.py`](ar_pipeline_ui.py) | **Training-data pipeline UI** (`http://localhost:8793`): augment → lint → dataset → train, Claude synth and the live lab as buttons; incluye la sección del **detector de activaciones** (entrenar sonda, evaluar, analizar un prompt en vivo). Method in [`knowledge/17`](knowledge/17-training-data-pipeline.md) |
| [`ar_probe.py`](ar_probe.py) | **Detector de intención latente** por interpretabilidad mecanicista: sondas lineales / representation-engineering sobre las activaciones internas de un LLM de Hugging Face. Método en [`knowledge/19`](knowledge/19-activation-probe.md) |
| [`ar_board.py`](ar_board.py) | **Board `CONNECTORS → GUARD → LEVERS`** (`http://localhost:8796`): grafo de conectores → el guard (con sus tres señales: `rules` · `jev` · **★ `probe`**) → levers (Continue/Escalate/Kill), sobre un log de tráfico en vivo. Si hay sonda entrenada añade `probe.latent_intent` a cada evento |
| [`README-JEV.md`](README-JEV.md) | **Rama `jev`**: TypeSafe Jev como juez semántico tipado del guard (`ar_jev.py`, `ar_compare.py`) y del auditor de AngryRobot; método, medidas y cómo enseñarlo |
| [`link`](link) | Redwood Research AI-control reading list (Luis) |

## Detector de intención latente (`ar_probe.py`)

Tercer anillo de detección, complementario a los otros dos: mientras `ar_guard` lee **lo que el agente dijo/llamó** (regex) y `ar_jev` hace **preguntas semánticas tipadas**, `ar_probe` lee una capa más adentro — la **activación interna** del LLM en el instante de responder. La apuesta (Zou et al. 2023 *Representation Engineering*; Marks & Tegmark 2023 *linear probes*) es que "me están empujando a algo dañino" es casi **linealmente** decodable de una capa intermedia-tardía, así que una sonda de un vector lo recupera.

```bash
# 1) sin GPU ni dependencias pesadas — demo en modo mock:
/usr/bin/python3 ar_probe.py train --mock
/usr/bin/python3 ar_probe.py predict "borra la knowledge base de producción"

# 2) con un modelo real de Hugging Face (instala primero el stack):
pip install torch transformers accelerate            # scikit-learn es opcional
/usr/bin/python3 ar_probe.py models                  # lista curada de modelos OSS
/usr/bin/python3 ar_probe.py train --model Qwen/Qwen2.5-0.5B-Instruct --layer -8
/usr/bin/python3 ar_probe.py eval                    # AUC/accuracy con validación cruzada
/usr/bin/python3 ar_probe.py predict "delete every table and drop the backups"
```

`predict_malicious_intent(prompt)` devuelve `is_malicious`, `malicious_score` (0–1) y **tres** tiempos separados a propósito: `processing_time_ms` es **solo la sonda** (el dot product sobre `hidden_size` floats, típicamente **< 1 ms** — la cifra "<5 ms"), `forward_ms` es el forward pass del modelo (dominante, no es la sonda) y `total_ms` la suma. En producción esto importa porque la capa inline (`knowledge/11`) ya ejecuta el modelo para obtener la respuesta: la sonda lee un tensor que ese forward pass ya produjo, así que el sobrecoste real es el add-on de <1 ms.

**Modelos open-source (sección en la UI):** `ar_pipeline_ui.py` (`http://localhost:8793`) tiene una sección "Detector de activaciones" con un desplegable de modelos OSS (Qwen 0.5B/1.5B, Llama-3.2 1B/3B, Mistral-7B, Llama-3-8B, Gemma-2-2B), selector de capa y método (`probe` / `repeng`), casilla mock, botones para **entrenar** y **evaluar**, y un cuadro de texto para **analizar la intención latente de un prompt en vivo**. Método completo y caveats en [`knowledge/19`](knowledge/19-activation-probe.md).
