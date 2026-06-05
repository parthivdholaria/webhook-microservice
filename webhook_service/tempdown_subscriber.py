from collections import defaultdict
from fastapi import FastAPI, Request, Response
from utils.signing import verify_signature

SECRET = "temp-client-down-secret"     

app = FastAPI()
seen = defaultdict(int)

@app.post("/hook")
async def hook(request: Request):
    raw = await request.body()                            # the EXACT bytes that were signed
    timestamp = request.headers.get("X-Webhook-Timestamp", "")
    signature = request.headers.get("X-Webhook-Signature", "")

    if not verify_signature(SECRET, timestamp, raw, signature):
        print("REJECTED: bad signature")
        return Response(status_code=401)

    body = await request.json()
    eid = body["event_id"]
    seen[eid] += 1
    if seen[eid] < 3:
        print(f"FAIL (pretending to be down): attempt {seen[eid]} for {eid}")
        return Response(status_code=500)
    print(f"OK verified + delivered {eid} on attempt {seen[eid]}")
    return {"ok": True}