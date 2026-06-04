from collections import defaultdict
from fastapi import FastAPI, Request, Response

app = FastAPI()
seen = defaultdict(int)

@app.post("/hook")
async def hook(request: Request):
    body = await request.json()
    eid = body["event_id"]
    seen[eid] += 1
    if seen[eid] < 3:
        print(f"FAIL (pretending to be down): attempt {seen[eid]} for {eid}")
        return Response(status_code=500)     # 5xx → our worker will retry
    print(f"OK delivered {eid} on attempt {seen[eid]}")
    return {"ok": True}