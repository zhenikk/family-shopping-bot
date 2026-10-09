# Speech comparison mode

Set SHOPPING_SPEECH_PROVIDER=race to compare local Whisper and Groq on the same prepared WAV. First non-empty successful transcription is delivered to the existing workflow. Losing inference continues for measurement, without changing the delivered draft. Only one local inference is permitted; it is skipped when busy. Global comparison pool has three threads. API billing continues even when the local result wins.

Owner admin displays the latest 100 samples with pagination and 90-day retention: request ID, Telegram message ID when available, user ID, language, release/commit, approximate audio duration, candidate durations/status, winner, time to winning transcript including download/preprocessing (excluding outer queue and DeepSeek/draft delivery), and normalized transcript equality. Candidate timings start when the candidate begins executing. No audio or transcript is persisted in analytics. A restart can leave pending samples; not a durable inference queue.

Exact normalized agreement is not accuracy. Evaluation requires a consented audio corpus with human reference transcripts and expected product lists. Measure WER/CER and product precision/recall separately. Do not silently use whichever result arrived first as the correctness reference. This mode spends CPU for benchmarking and may be disabled again after enough representative samples.
