# Product extraction comparison — 2026-10-09

30 hand-authored synthetic messages; 70 expected purchases. CPU, two Torch threads, macOS arm64. Models run sequentially after downloads. This is text extraction, not an audio-recognition accuracy test. No production model changes.

Same label `shopping product`, threshold 0.5 for both models. Matching: case-insensitive word-set Jaccard ≥0.5, greedy one-to-one. This permissive metric accepts partial names (e.g. фасоль vs фасоль біленько); strict full-message correctness is also reported. Synonym normalization is not applied, so valid canonicalized names may be penalized. Category accuracy uses the existing category rules after extraction, not the models. No parameter tuning on these cases.

| Engine | Correct / extra / missed | Precision | Recall | Strict messages | Category matched | Median / p95 ms | Peak process MiB |
|---|---|---|---|---|---|---|---|
| rules | 64 / 15 / 6 | 81.0% | 91.4% | 11/30 | 57/64 | 0.0 / 0.2 | 22 |
| gliner | 42 / 6 / 28 | 87.5% | 60.0% | 12/30 | 36/42 | 35.0 / 46.4 | 3012 |
| gliner2 | 70 / 3 / 0 | 95.9% | 100.0% | 26/30 | 62/70 | 36.8 / 51.4 | 3023 |

## Interpretation

GLiNER2 is the stronger candidate on this small set. Both mention extractors incorrectly include negated or already purchased items. GLiNER2 loses modifiers in some spans. Keep the draft confirmation; add intent/negation handling and evaluate on separately collected, consented real examples before adoption. Do not automatically deploy based on this test. Memory is peak whole Python process including model load; it is not steady-state model memory and macOS results do not prove Linux VPS usage.

Models: `urchade/gliner_multi-v2.1`, `fastino/gliner2-multi-v1`. Environment: Python 3.12, gliner 0.2.29, gliner2 2.0.0, torch 2.14.1, transformers 5.16.1. Runner and raw outputs are alongside this report.

## VPS capacity observation

Live VPS: 2 vCPU, 3916 MiB RAM; approximately 3117 MiB available at idle. Bot idle container ~22 MiB. Bot cgroup memory limit 3 GiB, swap disabled for container. Whisper small uses one job at a time with two CPU threads. Control sample: public whisper.cpp v1.9.4 samples/jfk.wav, 11 seconds English, total 13.276 seconds including 1.112 seconds model load. Approximate buffers/model sum ~0.73 GB (not measured peak RSS). One sample is not a load test; Ukrainian, longer recordings and host contention can change timing.

A continuously busy worker would process about 271 such jobs/hour (3600/13.276). For responsiveness plan substantially below saturation: 60–100 short jobs/hour is an initial operating target, not guaranteed capacity. Five simultaneous comparable jobs finish approximately at 13, 27, 40, 53 and 66 seconds; no download/network overhead included. Adding workers on two vCPU can increase contention rather than throughput.

There is no defensible maximum registered-user number from this test. Example assumption: 100 users × 2 voice jobs/day = 200 jobs/day, easily below aggregate theoretical throughput but burst timing still matters. 1000 users × 2/day with 20% arriving within one hour = 400/hour, above the observed one-worker theoretical capacity. Text/Web/API concurrent capacity was not load-tested.

## Scaling steps

1. Measure queue depth, oldest-job age, processing p50/p95, errors, CPU/RSS and HTTP latency without storing message content.
2. Retain one Whisper worker on current VPS. Add bounded queue, per-user fair scheduling, duplicate-job prevention, persistent jobs and overload feedback before open growth.
3. Run extraction in a separate worker/service with memory limits; current unoptimized ~3 GiB Python peaks plus Whisper do not fit comfortably in the present bot limit. Test quantization/ONNX or a larger host before adoption.
4. Scale voice workers on separate CPU capacity when sustained queue waiting exceeds the chosen UX target (e.g. p95 >30 seconds); validate target hardware first.
5. Test storage/API concurrency before multiple bot/API replicas: SQLite writes, durable job ownership and Telegram update consumption need coordination. Move to PostgreSQL/Redis or equivalent when observed contention and multi-worker requirements justify it.
