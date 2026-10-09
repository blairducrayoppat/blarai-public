"""API probe: what does ContinuousBatchingPipeline expose on this genai build?

Used once to settle the adapter's contract (result shape, streamer behaviour,
metrics available as an MTP-engaged witness) before any measurement.
"""
import sys, time, json
import openvino_genai as g

model_dir = sys.argv[1]
mtp = sys.argv[2] == "on"
sc = g.SchedulerConfig()
sc.cache_size = 3
sc.enable_prefix_caching = False
import os
sc.max_num_seqs = int(os.environ.get("PROBE_SEQS", "1"))
sc.cache_size = int(os.environ.get("PROBE_CACHE", "3"))
props = {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_PRECISION_HINT": "f16",
         "GPU_ENABLE_SDPA_OPTIMIZATION": "ON", "CACHE_DIR": "",
         "KV_CACHE_PRECISION": "f16", "DYNAMIC_QUANTIZATION_GROUP_SIZE": 0}
if mtp:
    props["draft_model"] = g.draft_model(model_dir, "GPU")
t0 = time.perf_counter()
pipe = g.ContinuousBatchingPipeline(model_dir, sc, "GPU", props)
print("load_s", round(time.perf_counter() - t0, 1))
prompt = ("<|im_start|>system\nYou are concise.<|im_end|>\n<|im_start|>user\n"
          "List three prime numbers and say why they are prime.<|im_end|>\n"
          "<|im_start|>assistant\n<think>\n\n</think>\n\n")
cfg = g.GenerationConfig()
cfg.max_new_tokens = 64
cfg.do_sample = False
cfg.apply_chat_template = False
if mtp:
    cfg.num_assistant_tokens = 3
    cfg.assistant_confidence_threshold = 0.0
chunks = []
def streamer(c):
    chunks.append(c)
    return g.StreamingStatus.RUNNING
for i in range(2):
    chunks.clear()
    t = time.perf_counter()
    res = pipe.generate([prompt], [cfg], streamer)
    dt = time.perf_counter() - t
    r = res[0]
    print("run", i, "type", type(res), type(r), "secs", round(dt, 2))
    print([a for a in dir(r) if not a.startswith("_")])
    print("texts", repr(getattr(r, "m_generation_ids", None))[:300])
    print("ids", len(getattr(r, "m_generation_ids", [])), "first chunk", repr(chunks[:1]), "n_chunks", len(chunks))
    pm = getattr(r, "perf_metrics", None)
    if pm is not None:
        print("perf", [a for a in dir(pm) if not a.startswith("_")])
        try:
            print("num_generated", pm.get_num_generated_tokens(), "ttft", pm.get_ttft().mean, "tpot", pm.get_tpot().mean)
        except Exception as e:
            print("pm err", e)
print("metrics", pipe.get_metrics())
print("spec api", [a for a in dir(pipe) if "spec" in a.lower() or "draft" in a.lower()])
print("results attrs", [a for a in dir(g) if "peculative" in a or "ssist" in a or "Draft" in a])
em = res[0].extended_perf_metrics
print("ext type", type(em), [a for a in dir(em) if not a.startswith("_")] if em is not None else None)
if em is not None:
    for a in dir(em):
        if a.startswith("_"): continue
        try:
            v = getattr(em, a)
            print(" ", a, v() if callable(v) else v)
        except Exception as e:
            print(" ", a, "ERR", e)
