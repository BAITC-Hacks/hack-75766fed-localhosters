---
name: gpu-remote
description: Run heavy ML work (model training, fine-tuning, hyperparameter search, CUDA/GPU jobs, full-dataset feature pipelines, TimesFM or other foundation-model inference, anything longer than ~2 min or needing more than ~8 GB RAM) on the team's remote Brev GPU instance instead of the local Mac. Use whenever a task would train or evaluate a model at scale, needs a GPU, or the user says "run on the GPU", "run on Brev", or "run remotely".
---

# Remote GPU execution (Brev)

The local Mac is for editing code, light analysis and small data checks. Heavy compute goes to the Brev instance.

| | |
|---|---|
| SSH host | `nursing-bronze-unicorn` (Brev ID `rq9r2us2x`) |
| GPU | 1x NVIDIA RTX PRO 6000 Blackwell, 96 GB |
| Disk | ~660 GB free |
| User / Python | `shadeform`, system Python 3.10 (don't install into it) |
| Remote project dir | `~/project` |
| Remote venv | `~/project/.venv` |

If the instance is recreated, update the host and ID in this file.

## 1. Check the box is up

```bash
brev ls | grep rq9r2us2x
```

- If it's `STOPPED`, run `brev start rq9r2us2x`, then poll `brev ls` until it shows `RUNNING  COMPLETED  READY`.
- If ssh can't resolve the host, run `brev refresh`.
- Quick check: `ssh nursing-bronze-unicorn 'nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader'`

Before starting a job, check `nvidia-smi` for other running processes. A teammate may be using the GPU.

## 2. Sync code (local → remote)

Run from the repo root:

```bash
rsync -az --delete \
  --exclude .git --exclude '.venv*' --exclude __pycache__ --exclude .DS_Store \
  --exclude outputs --exclude logs --exclude checkpoints \
  ./ nursing-bronze-unicorn:~/project/
```

- The local repo is the source of truth. Never edit code on the box; edit locally and re-sync.
- `outputs/`, `logs/` and `checkpoints/` are excluded so `--delete` never wipes remote results.

## 3. First-time environment setup (only if `~/project/.venv` is missing)

```bash
ssh nursing-bronze-unicorn 'cd ~/project && python3 -m venv .venv && . .venv/bin/activate && pip install -U pip wheel'
```

Then install deps. The repo has no requirements file yet, so install what the job imports, e.g.:

```bash
ssh nursing-bronze-unicorn 'cd ~/project && . .venv/bin/activate && pip install torch pandas numpy scikit-learn lightgbm pyarrow requests'
```

Before launching anything that uses the GPU, check that torch can see it:

```bash
ssh nursing-bronze-unicorn 'cd ~/project && . .venv/bin/activate && python -c "import torch;print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"'
```

If you add a requirements file later, install from it here instead.

## 4. Run the job

**Short (< ~2 min):** run it in the foreground:

```bash
ssh nursing-bronze-unicorn 'cd ~/project && . .venv/bin/activate && python -m windagent.<module> <args>'
```

**Long:** run it detached, log to a file, and poll the log. Don't hold an SSH session open for the whole run.

```bash
RUN=$(date +%Y%m%d-%H%M%S)-<short-name>
ssh nursing-bronze-unicorn "cd ~/project && mkdir -p logs outputs/$RUN && . .venv/bin/activate && \
  nohup python -u -m windagent.<module> --out outputs/$RUN <args> > logs/$RUN.log 2>&1 & echo \$! > logs/$RUN.pid"
```

To poll, check progress with `ssh nursing-bronze-unicorn "tail -n 30 ~/project/logs/$RUN.log"` and whether the process is still running with `ssh nursing-bronze-unicorn "ps -p \$(cat ~/project/logs/$RUN.pid) >/dev/null && echo running || echo done"`. When polling, use the Monitor tool or a background Bash loop rather than repeated foreground sleeps.

Rules:
- Write every artifact (models, predictions, metrics) under `outputs/<RUN>/`.
- Set seeds and log the config at the start of the run so results are reproducible.
- Use `python -u` so the log is written unbuffered.

## 5. Pull results back

```bash
rsync -az nursing-bronze-unicorn:~/project/outputs/<RUN>/ ./outputs/<RUN>/
rsync -az nursing-bronze-unicorn:~/project/logs/<RUN>.log ./logs/
```

Pull back only what's needed (metrics, predictions, small models). Leave large checkpoints on the box unless asked.

## 6. Report

Tell the user:
- the run name
- the command that was run
- the key metrics
- where the outputs are, both locally and on the box

If the run failed, show the tail of the log.

## Cost

The instance bills while it runs. When a work session is done and no jobs are running, remind the user they can stop it with `brev stop rq9r2us2x`. Never stop or delete it without asking.
