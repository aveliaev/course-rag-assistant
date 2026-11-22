#!/bin/sh
set -eu
cd "$(dirname "$0")"

run_dir=${1:-runs/b0-kt3}
python_bin=.venv/bin/python
if [ ! -x "$python_bin" ]; then
    uv venv --python 3.12 .venv
fi
uv pip sync --require-hashes --python "$python_bin" infra/requirements-lock.txt
uv pip install --python "$python_bin" --no-deps --editable .
git cat-file -e 6c56bcbcf06f6cba296bb9674a43bf6739887cc0:KT-2/dev_148.jsonl
docker compose -f infra/compose.yaml up -d --wait
"$python_bin" -m fkn_assistant.index
calibration="$run_dir/calibration/calibration.json"
if [ ! -f "$calibration" ] && [ -f infra/retrieval-calibration.json ]; then
    mkdir -p "$run_dir/calibration"
    cp infra/retrieval-calibration.json "$calibration"
fi
if [ -f "$calibration" ]; then
    cp "$calibration" .cache/retrieval.json
else
    "$python_bin" -m fkn_assistant.evaluation.runner --variant rag-b0 --dataset calibrate --output "$run_dir/calibration"
fi
"$python_bin" -m unittest discover -s tests
"$python_bin" -m fkn_assistant.evaluation.runner --variant rag-b0 --dataset dialogues --output "$run_dir/dialogues"
"$python_bin" -m fkn_assistant.evaluation.runner --variant prompt-only --dataset smoke --repeats 1 --output "$run_dir/prompt-smoke"
"$python_bin" -m fkn_assistant.evaluation.runner --variant rag-b0 --dataset smoke --repeats 1 --output "$run_dir/smoke"
"$python_bin" -m fkn_assistant.evaluation.runner --variant rag-b0 --dataset dev --repeats 3 --output "$run_dir/dev"
"$python_bin" -m fkn_assistant.evaluation.report "$run_dir/dev" > "$run_dir/results-rag.md"
"$python_bin" -m fkn_assistant.evaluation.report "$run_dir/dev" --review > "$run_dir/dev/review.md"
