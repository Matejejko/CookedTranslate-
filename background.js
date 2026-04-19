// ============================================================
// CookedTranslate - background.js
// ============================================================
// API key lives in config.js — add config.js to .gitignore.
// ============================================================

importScripts("config.js");

// CONFIG is injected by config.js (loaded first via manifest.json)
const TARGET_LANG = CONFIG.TARGET_LANG;
const GEMINI_MODEL = CONFIG.GEMINI_MODEL;
const GEMINI_API_KEY = CONFIG.GEMINI_API_KEY;

// Per-videoId state:
//   not in map    -> never attempted
//   "in-progress" -> running, skip duplicates
//   "done"        -> completed, skip
//   "failed"      -> permanently failed, skip until extension reload
const videoState = new Map();

console.log("background.js loaded");

chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
        if (
            !details.url.includes("timedtext") ||
            !details.url.includes("fmt=json3")
        ) {
            return;
        }

        const videoId = new URL(details.url).searchParams.get("v");
        if (!videoId) return;

        if (videoState.has(videoId)) return;

        videoState.set(videoId, "in-progress");
        console.log(`Starting translation for video ${videoId}`);

        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            if (!tabs[0]?.id) {
                videoState.delete(videoId);
                return;
            }
            handleCaptions(details.url, tabs[0].id, videoId);
        });
    },
    { urls: ["*://*.youtube.com/api/timedtext*"] },
);

async function handleCaptions(url, tabId, videoId) {
    try {
        const res = await fetch(url);
        const data = await res.json();

        const segments = [];
        for (const event of data.events || []) {
            if (!event.segs) continue;
            let text = "";
            for (const seg of event.segs) {
                text += seg.utf8 || "";
            }
            text = text.trim();
            if (!text) continue;

            segments.push({
                start: event.tStartMs || 0,
                dur: event.dDurationMs || 2000,
                text: text,
            });
        }

        if (segments.length === 0) {
            console.log("No caption segments found");
            videoState.set(videoId, "done");
            return;
        }

        console.log(`Parsed ${segments.length} segments, translating...`);

        const translated = await translateSegments(segments);
        if (!translated) {
            console.error("Translation failed, marking as failed");
            videoState.set(videoId, "failed");
            return;
        }

        console.log(`Got ${translated.length} segments, sending to tab`);
        const sent = await sendToTab(tabId, {
            type: "TRANSLATED_SEGMENTS",
            segments: translated,
        });

        videoState.set(videoId, sent ? "done" : "failed");
    } catch (err) {
        console.error("handleCaptions error:", err);
        videoState.set(videoId, "failed");
    }
}

// Retry sendMessage because content.js may not be injected yet on SPA nav.
async function sendToTab(tabId, msg, attempts = 6) {
    for (let i = 0; i < attempts; i++) {
        try {
            await chrome.tabs.sendMessage(tabId, msg);
            return true;
        } catch (err) {
            if (i === attempts - 1) {
                console.error(
                    `Failed to send to tab after ${attempts} attempts:`,
                    err.message,
                );
                return false;
            }
            await new Promise((r) => setTimeout(r, 500));
        }
    }
    return false;
}

async function translateSegments(segments, attempt = 1) {
    const MAX_ATTEMPTS = 3;

    const numbered = segments.map((s, i) => `[${i + 1}] ${s.text}`).join("\n");

    const prompt = `Translate each numbered segment below to ${TARGET_LANG}.
Return EXACTLY the same number of lines, in the same format: [N] translation
Do not merge or split segments. Do not add commentary. Keep bracketed numbers intact.

${numbered}`;

    let res;
    try {
        res = await fetch(
            `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    contents: [{ parts: [{ text: prompt }] }],
                }),
            },
        );
    } catch (err) {
        console.error("Network error calling Gemini:", err);
        return null;
    }

    const data = await res.json();

    if (data.error) {
        console.error(`Gemini error (attempt ${attempt}):`, data.error);

        if (attempt < MAX_ATTEMPTS && data.error.code === 503) {
            const delayMs = 2000 * attempt;
            console.log(`503 overload - retrying in ${delayMs}ms`);
            await new Promise((r) => setTimeout(r, delayMs));
            return translateSegments(segments, attempt + 1);
        }
        return null;
    }

    const responseText = data.candidates?.[0]?.content?.parts?.[0]?.text;
    if (!responseText) {
        console.error("Gemini returned no text. Full response:", data);
        return null;
    }

    const translationMap = new Map();
    const lineRegex = /^\s*\[(\d+)\]\s*(.+?)\s*$/;
    for (const line of responseText.split("\n")) {
        const m = line.match(lineRegex);
        if (m) {
            translationMap.set(parseInt(m[1], 10), m[2]);
        }
    }

    if (translationMap.size !== segments.length) {
        console.warn(
            `Segment count mismatch: sent ${segments.length}, got ${translationMap.size}. ` +
                `Missing segments will show original text.`,
        );
    }

    return segments.map((s, i) => ({
        start: s.start,
        dur: s.dur,
        text: translationMap.get(i + 1) || s.text,
    }));
}
