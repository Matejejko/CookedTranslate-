// ============================================================
// CookedTranslate - content.js
// ============================================================

let segments = [];
let overlay = null;
let videoEl = null;
let rafId = null;

chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "TRANSLATED_SEGMENTS") {
        console.log(
            "[CookedTranslate] Received",
            msg.segments.length,
            "segments",
        );
        segments = msg.segments;
        ensureOverlay();
        startSync();
    }
});

function ensureOverlay() {
    if (overlay && document.body.contains(overlay)) return;

    overlay = document.createElement("div");
    overlay.id = "cooked-translate-overlay";
    Object.assign(overlay.style, {
        position: "fixed",
        left: "50%",
        transform: "translateX(-50%)",
        bottom: "15%",
        maxWidth: "70%",
        padding: "8px 16px",
        background: "rgba(0, 0, 0, 0.75)",
        color: "white",
        fontSize: "22px",
        fontFamily: "sans-serif",
        textAlign: "center",
        borderRadius: "4px",
        zIndex: "9999",
        pointerEvents: "none",
        lineHeight: "1.3",
        whiteSpace: "pre-wrap",
    });
    document.body.appendChild(overlay);
}

function startSync() {
    videoEl = document.querySelector("video");
    if (!videoEl) {
        // YouTube's video element may not be ready yet on fast navigations.
        // Retry shortly.
        setTimeout(startSync, 500);
        return;
    }

    if (rafId) cancelAnimationFrame(rafId);

    const tick = () => {
        updateOverlay();
        rafId = requestAnimationFrame(tick);
    };
    tick();
}

function updateOverlay() {
    if (!videoEl || !overlay || segments.length === 0) return;

    const currentMs = videoEl.currentTime * 1000;

    // Linear scan. Fine for a few thousand segments. If this ever gets
    // slow, switch to binary search + last-index cache.
    let active = null;
    for (const s of segments) {
        if (currentMs >= s.start && currentMs < s.start + s.dur) {
            active = s;
            break;
        }
    }

    const newText = active ? active.text : "";
    if (overlay.textContent !== newText) {
        overlay.textContent = newText;
    }
}

// Clean up on navigation (YouTube is a SPA, so `unload` isn't reliable).
// For now we just let segments persist until a new TRANSLATED_SEGMENTS
// message comes in. Good enough for prototype.
