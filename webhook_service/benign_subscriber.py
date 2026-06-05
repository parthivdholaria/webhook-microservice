from collections import defaultdict
from fastapi import FastAPI, Request, Response
from utils.signing import verify_signature

SECRET = "benign-client-secret"     # the same secret used when registering

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
    print(f"OK verified + delivered {eid} on attempt {seen[eid]}")
    return {"ok": True}