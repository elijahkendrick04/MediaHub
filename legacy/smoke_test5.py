"""
Smoke Test 5: Pipeline with fetch_pbs=True
Checks:
- pb_audit is present and correct type
- decisions > 0
- needs_verification count
- verified count (should be > 0 after parser + name fix)
- cache_hits / cache_misses tracking
- elapsed time
"""
import sys, time, json
sys.path.insert(0, '/home/user/workspace/swim-content')

ZIP_PATH = '/home/user/workspace/Meet-Results-Swansea-Aquatics-May-Long-Course-2026-02May2026-001.zip'

with open(ZIP_PATH, 'rb') as f:
    file_bytes = f.read()

steps = []
def step(msg):
    steps.append(msg)
    print(f"  [step] {msg}")

from swim_content_v4.pipeline_v4 import run_pipeline_v4

t0 = time.time()
run = run_pipeline_v4(
    file_bytes=file_bytes,
    filename='Meet-Results-Swansea-Aquatics-May-Long-Course-2026-02May2026-001.zip',
    fetch_pbs=True,
    use_pb_cache=True,
    progress_cb=step,
    run_id='smoke_test5',
)
elapsed = time.time() - t0

print(f"\n--- Smoke Test 5 Results ---")
print(f"elapsed:            {elapsed:.1f}s")
print(f"cards:              {len(run.cards)}")
print(f"pb_audit type:      {type(run.pb_audit).__name__}")

if run.pb_audit is None:
    print("ERROR: pb_audit is None!")
    sys.exit(1)

audit = run.pb_audit
print(f"pb_audit present:   True")
print(f"swimmers_total:               {audit.swimmers_total}")
print(f"swimmers_matched_verified:    {audit.swimmers_matched_verified}")
print(f"swimmers_needs_verification:  {audit.swimmers_needs_verification}")
print(f"swimmers_no_id:               {audit.swimmers_no_id}")
print(f"swimmers_fetch_failed:        {audit.swimmers_fetch_failed}")
print(f"pb_decisions_count:           {audit.pb_decisions_count}")
print(f"pb_confirmed_count:           {audit.pb_confirmed_count}")
print(f"pb_likely_count:              {audit.pb_likely_count}")
print(f"pb_not_pb_count:              {audit.pb_not_pb_count}")
print(f"pb_unverified_count:          {audit.pb_unverified_count}")
print(f"pb_suppressed_count:          {audit.pb_suppressed_count}")
print(f"cache_hits:                   {audit.cache_hits}")
print(f"cache_misses:                 {audit.cache_misses}")
print(f"fetch_total_seconds:          {audit.fetch_total_seconds}")
print(f"fetch_budget_exceeded:        {audit.fetch_budget_exceeded}")

# Assertions
assert audit.swimmers_total == 36, f"Expected 36 swimmers, got {audit.swimmers_total}"
assert audit.swimmers_matched_verified > 0, "Expected some verified swimmers"
assert audit.pb_decisions_count > 0, "Expected some PB decisions"
print(f"\n[assertions passed]")

# Sample PBAudit for one verified swimmer
print(f"\n--- Per-swimmer sample (first with verified identity) ---")
verified_swimmers = [sa for sa in audit.per_swimmer if sa.identity and sa.identity.method == 'asa_id_verified']
print(f"Verified swimmer count: {len(verified_swimmers)}")
if verified_swimmers:
    sa = verified_swimmers[0]
    sample = {
        "asa_id": sa.asa_id,
        "hy3_name": sa.hy3_name,
        "sr_name": sa.sr_name,
        "identity": {
            "method": sa.identity.method,
            "canonical_hy3_name": sa.identity.canonical_hy3_name,
            "canonical_sr_name": sa.identity.canonical_sr_name,
            "confidence": sa.identity.confidence,
            "safe_to_use": sa.identity.safe_to_use,
            "notes": sa.identity.notes,
        },
        "events_fetched_count": len(sa.events_fetched),
        "pb_decisions_count": len(sa.pb_decisions),
        "fetch_ok": sa.fetch_ok,
        "pb_decisions_sample": [
            {
                "status": d.status,
                "event": d.event,
                "course": d.course,
                "current_time_display": d.current_time_display,
                "previous_pb": d.previous_pb,
                "audit_trail": d.audit_trail[:3],
            }
            for d in sa.pb_decisions[:3]
        ],
    }
    with open('/home/user/workspace/swim-content/smoke5_sample_audit.json', 'w') as f:
        json.dump(sample, f, indent=2, default=str)
    print(f"[saved PBAudit sample to smoke5_sample_audit.json]")
    print(f"  asa_id={sa.asa_id}, hy3_name={sa.hy3_name!r}, sr_name={sa.sr_name!r}")
    print(f"  identity.method={sa.identity.method}, decisions={len(sa.pb_decisions)}")

# Look for CONFIRMED_PB decisions
print(f"\n--- CONFIRMED_PB decisions ---")
confirmed = []
for sa in audit.per_swimmer:
    for d in sa.pb_decisions:
        if d.status == 'CONFIRMED_PB':
            confirmed.append((sa, d))
print(f"CONFIRMED_PB count: {len(confirmed)}")
if confirmed:
    sa, d = confirmed[0]
    sample_cpb = {
        "asa_id": sa.asa_id,
        "hy3_name": sa.hy3_name,
        "sr_name": sa.sr_name,
        "verdict": d.status,
        "event": d.event,
        "course": d.course,
        "current_time_display": d.current_time_display,
        "previous_pb": d.previous_pb,
        "delta_seconds": d.delta_seconds,
        "improvement_percentage": d.improvement_percentage,
        "confidence": d.confidence,
        "safe_to_post": d.safe_to_post,
        "reason": d.reason,
        "evidence": d.evidence,
        "audit_trail": d.audit_trail,
    }
    with open('/home/user/workspace/swim-content/smoke5_confirmed_pb.json', 'w') as f:
        json.dump(sample_cpb, f, indent=2, default=str)
    print(f"[saved CONFIRMED_PB sample to smoke5_confirmed_pb.json]")
    print(f"  {sa.hy3_name}: {d.event} {d.course} {d.current_time_display} (prev: {d.previous_pb})")

print(f"\nSmoke Test 5: PASS")
