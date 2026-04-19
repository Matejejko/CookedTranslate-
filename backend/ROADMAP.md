# CookedTranslate — Dev Roadmap

Honest version. Time estimates assume you code in evenings/weekends, not full-time. Double them if you're learning something new along the way. Triple them if you keep getting sidetracked.

## Ground rules

1. **Ship each phase before starting the next.** A half-finished Phase 3 is worth less than a finished Phase 2.
2. **Every phase ends with you actually using it.** Not "it works on my machine for one video," but "I watched a whole video end-to-end and didn't want to punch the screen."
3. **Don't build for users you don't have.** You will want to. Don't.
4. **Cut scope, not quality.** If a phase is dragging, remove features — don't ship broken ones.

---

## Phase 0 — Proof of concept ✅ DONE

What you already have:
- Step 1 script: YouTube video → Japanese audio → Gemini → English segments
- Step 2 backend: FastAPI with streaming job model, chunking, parallel processing
- Verified Gemini's output quality on real Japanese audio

**You are here.**

---

## Phase 1 — Backend works end-to-end on your Windows box
**~1 evening** if nothing breaks weirdly. **~2-3** if it does.

- [ ] Run step 2 backend. Confirm the full pipeline on a 10-minute video.
- [ ] Watch the segment list grow in real time via polling.
- [ ] Cancel a job mid-flight, verify temp files clean up.
- [ ] Hit it with a broken video ID (deleted/private/age-gated) and confirm it fails gracefully.
- [ ] Verify concurrent jobs work — fire two at once, both should complete.

**Exit criterion:** you can `curl -X POST /jobs` for any 10-minute Japanese video and 60 seconds later have streaming English segments in your terminal.

**Gotchas to expect:**
- Windows event loop differences (`asyncio.create_subprocess_exec` on Windows needs `ProactorEventLoop`, which uvicorn should use by default — but if you see weird errors, this is the first suspect).
- yt-dlp version drift — if YouTube changes something and your install is old, downloads break. `pip install -U yt-dlp` fixes it.
- Long videos hitting Gemini TPM caps. A 60-min video at 32 tokens/sec is 115K tokens per chunk — still under 250K TPM cap but close.

---

## Phase 2 — Caching
**~1 evening.** Don't skip, don't postpone.

You've seen what one dev day of hitting Gemini looks like. Add SQLite cache now.

- [ ] `cache.py` module wrapping SQLite. One table: `(video_id, target_lang, segments_json, created_at)`.
- [ ] Pipeline checks cache before creating job; if hit, synthesize a "done" job immediately.
- [ ] Cache invalidation: none for now. Manual `DELETE /cache/{videoId}` endpoint for debug.
- [ ] Disk eviction: LRU when cache exceeds configurable size (default 500MB).
- [ ] Serve cached jobs instantly — status = "done", full segments array, no Gemini call.

**Exit criterion:** second view of the same video returns segments in <200ms, zero Gemini tokens spent.

**Why here, not later:** every phase after this one involves repeated testing. Without cache you'll burn through quota and your own money debugging the extension.

---

## Phase 3 — Chunk overlap to fix boundary garbling
**~2-3 evenings.** This is the first phase with real engineering difficulty.

Right now, segments at chunk boundaries can be truncated mid-sentence or garbled because Gemini can't hear across chunk edges.

- [ ] Add 5-second overlap: chunk N covers [N*30, N*30+35].
- [ ] Dedupe segments at boundaries. Two options:
  - **Simple:** drop segments from chunk N+1 whose `start < N*30 + 5`. Loses some legit content.
  - **Smart:** compute text similarity between end-of-N and start-of-N+1, merge or drop. More work.
- [ ] Measure: pick 3 test videos, count boundary-garbled segments before/after. If the simple fix knocks it down by 80%, ship it and move on.

**Exit criterion:** watching a chunk boundary in a real video doesn't produce a visible glitch.

**Honest note:** this is where you'll be tempted to rabbit-hole. Don't. "Mostly okay at boundaries" is fine for v1.

---

## Phase 4 — Extension rewrite
**~3-5 evenings.**

Throw away most of what you have. New flow:

- [ ] `manifest.json`: permissions for `activeTab`, `storage`, `scripting`, host permission for YouTube, plus host permission for your backend URL.
- [ ] `background.js`: detect video navigation (`chrome.webNavigation.onHistoryStateUpdated` or listen for YouTube's SPA events), extract videoId from URL, call `POST /jobs`, poll `GET /jobs/{id}` every 2s, forward segments to content script.
- [ ] `content.js`: create overlay div, sync to `video.currentTime`, render active segment. Delete current version entirely.
- [ ] `options.html`: backend URL, target language, enable/disable.
- [ ] Cancel job on tab close / video navigation.
- [ ] Handle failure states: show "translation failed" in overlay, link to retry.

**Exit criterion:** install extension in Chrome, visit a Japanese YouTube video, English subs appear in sync within 30 seconds of page load.

**Gotchas:**
- YouTube SPA navigation is fiddly. The `videoId` changes but the page doesn't fully reload.
- Fullscreen breaks your overlay (position: fixed escapes fullscreen). Not critical for v1.
- Your overlay will clash with YouTube's own captions if they're also on. Add a toggle.

---

## Phase 5 — Dockerize and deploy to your Ubuntu server
**~2 evenings if you're comfortable with k3s, ~1 week if you're learning it.**

- [ ] `Dockerfile`: Python base, install ffmpeg + deps, copy code, ENTRYPOINT uvicorn.
- [ ] Build locally, run container locally, point extension at it. Should work identically.
- [ ] Push image to a registry (GHCR free, Docker Hub free).
- [ ] k3s manifest: Deployment + Service + maybe an Ingress. Pull image from registry.
- [ ] Persistent volume for SQLite cache + optional HTTPS via cert-manager if you want a real domain.
- [ ] Point extension at `https://your-domain.example.com` instead of `localhost:8000`.

**Exit criterion:** your Windows machine off, laptop on airplane wifi, extension still works because backend lives on the Ubuntu box.

**What you're learning if this is new:**
- Container networking (why localhost inside the container isn't localhost outside)
- k3s vs standalone Docker (you chose k3s, commit to it)
- Secrets management (where does GEMINI_API_KEY live — almost certainly a Kubernetes Secret, not the image)

---

## Phase 6 — Open source release
**~1 week, but a lot of it is non-coding.**

The difference between "code on my server" and "GitHub project people can install" is huge.

- [ ] README: what it is, screenshot/gif, "how to install" section with real steps.
- [ ] `LICENSE` — MIT unless you have a reason otherwise.
- [ ] `CONTRIBUTING.md` — even if nobody contributes, having it makes the repo look serious.
- [ ] Issue templates.
- [ ] GitHub Actions: at minimum, lint + basic test on push. Extra: build and push Docker image on tag.
- [ ] Docker Compose for people who don't run k3s. One `docker-compose up` should give them a working backend.
- [ ] Document the "I don't have a server" path: running the backend on localhost.
- [ ] Chrome Web Store submission — optional, has a $5 one-time fee, requires privacy policy + screenshots.
- [ ] First real tag: `v0.1.0`.

**Exit criterion:** a stranger with moderate technical skill can clone your repo, read the README, and have a working system within 30 minutes.

**Things you'll hate writing but matter:**
- Privacy policy (if Web Store). You process YouTube URLs and audio on a server, you need one.
- Terms / disclaimer. "This tool may violate YouTube's ToS. Use at your own risk."

---

## Phase 7 — Polish based on actually using it
**Indefinite. This is where most side projects die.**

Make a list during Phases 1-6 of things that annoyed you. Fix them in priority order. Do not add new features from an imaginary roadmap — fix real annoyances from actual use.

Examples of real annoyances (not inventions):
- "The overlay covers the subscribe button."
- "When I pause and seek back, sometimes the overlay stays frozen."
- "Japanese videos work great, German videos mess up proper nouns."
- "My laptop screen is smaller than my desktop and the font is too big."

Budget: **one evening per annoyance**. If something takes more than that, either it's actually two annoyances (split it) or it's not worth it yet.

---

## Phase 8 (conditional) — Turn it into a business
**Only start if:**
- You've been personally using v1 for 3+ months
- At least 5 technical friends have installed it without you hand-holding
- You have unsolicited requests from non-technical people who want access

If all three are true, do this:
1. **Stop adding features.** Fork the repo, start a `business/` branch.
2. Backend runs on your infrastructure, not the user's. User auth (Clerk, Auth0, or DIY). User quotas. Rate limiting.
3. Payment (Stripe). Tiered plans.
4. Legal review. Especially around YouTube ToS.
5. Abandon the "open source" version, or keep maintaining it — accept the cost.

Time: 3-6 months of focused work. **If you're not ready to commit to that, stay in Phase 7 forever and that's fine.**

---

## Total estimates

| Phase | Evenings | Cumulative | You'll actually take |
|---|---|---|---|
| 1 | 1-3 | 1-3 | 3-5 |
| 2 | 1 | 2-4 | 4-7 |
| 3 | 2-3 | 4-7 | 7-12 |
| 4 | 3-5 | 7-12 | 12-20 |
| 5 | 2-7 | 9-19 | 15-30 |
| 6 | 5-7 | 14-26 | 25-40 |
| 7 | ongoing | - | - |

**Realistic MVP (Phase 4 done, usable daily): 3-6 weeks of evenings.**
**Realistic open-source v0.1 (Phase 6 done): 2-4 months of evenings.**

These numbers aren't conservative. Most side projects take 2-3x what their authors expect.

---

## Anti-goals (things to NOT do, especially early)

- ❌ Mobile app. You said extension; stick to it.
- ❌ Supporting Twitch/Vimeo/TikTok. YouTube only for v1.
- ❌ Translating to 50 languages. English and maybe one more for v1.
- ❌ A "smart" UI with history, favorites, search. You're watching YouTube, not using a separate app.
- ❌ Users, accounts, billing — before you have users asking for them.
- ❌ Rewriting the backend in Go / Rust / whatever because Python feels slow. It's not slow; network + Gemini latency dominate.
- ❌ Adding a frontend website. The extension IS the frontend.

---

## Things to revisit at each phase boundary

Before starting a new phase, ask yourself:

1. **Am I still using it?** If you haven't opened a Japanese video with this extension in 2 weeks, stop and figure out why.
2. **Is the previous phase actually done?** Not "works sometimes," but "I'd be embarrassed to say it's broken."
3. **Has the goal changed?** It's allowed to. Just make it explicit.

If any answer is "no", don't start the next phase yet. Fix the real thing first.
