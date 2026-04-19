# CookedTranslate — Step 2 backend

FastAPI service that downloads YouTube audio, chunks it, and streams
translated segments as Gemini finishes each chunk.

## Run

```bash
# From the backend/ directory
pip install -r requirements.txt

# PowerShell:
$env:GEMINI_API_KEY = "your_key"

# or cmd.exe:
# set GEMINI_API_KEY=your_key

# or Linux/mac:
# export GEMINI_API_KEY=your_key

uvicorn app:app --reload --port 8000
```

Server starts on http://localhost:8000.

## Test end-to-end with curl

```bash
# Start a job
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d "{\"video_id\": \"w-u_NrA9owA\", \"target_lang\": \"English\"}"

# Response: { "job_id": "abc123...", "status": "pending", ... }

# Poll
curl http://localhost:8000/jobs/abc123...

# You'll see status go: pending -> downloading -> transcribing -> done
# `segments` array grows as chunks complete.

# Cancel (optional)
curl -X DELETE http://localhost:8000/jobs/abc123...
```

PowerShell users can use `Invoke-RestMethod` instead:

```powershell
$r = Invoke-RestMethod -Method POST -Uri http://localhost:8000/jobs `
  -ContentType "application/json" `
  -Body '{"video_id": "w-u_NrA9owA", "target_lang": "English"}'
$jobId = $r.job_id

# Poll in a loop:
while ($true) {
  $s = Invoke-RestMethod -Uri "http://localhost:8000/jobs/$jobId"
  Write-Host "$($s.status) $([int]($s.progress * 100))% segments=$($s.segments.Count)"
  if ($s.status -in 'done','failed','cancelled') { break }
  Start-Sleep -Seconds 2
}
$s.segments | Select-Object -First 5 | Format-List
```

## What to watch

Server logs show each chunk being processed in parallel and emitted
in order. Look for:

    pipeline: job abc: emitted chunk 1/12 (+4 segs)
    pipeline: job abc: emitted chunk 2/12 (+5 segs)

If chunk 2 finishes before chunk 1, we still emit chunk 1 first.
Keeps the segment list ordered for the client.

## Known limits

- No persistence. Restart = jobs lost.
- No cache. Every call re-hits Gemini. Added in step 3.
- `find_live` dedup is stringly-typed and naive. Good enough for dev.
- No auth. Anyone reaching port 8000 can spend your tokens. Lock this
  down before exposing beyond localhost.
