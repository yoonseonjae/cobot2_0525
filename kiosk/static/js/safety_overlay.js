/* ─────────────────────────────────────────────────────────────────────
 * 키오스크 PC 안전모드 오버레이
 *  - 대시보드가 Firebase /safety_mode.json 에 {mode, message} 를 publish
 *  - 700ms 마다 폴링하여 화면에 노란/빨강 outliner 배너 표시
 * ───────────────────────────────────────────────────────────────────── */
(function () {
    const FIREBASE_URL =
        "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/safety_mode.json";

    // overlay element 주입 (모든 페이지 공통)
    function ensureOverlay() {
        let el = document.getElementById("safety-frame-overlay");
        if (el) return el;
        el = document.createElement("div");
        el.id = "safety-frame-overlay";
        el.innerHTML = `<div class="safety-badge"><span class="main">정상</span><span class="sub"></span></div>`;
        document.body.appendChild(el);
        return el;
    }

    function applyMode(payload) {
        const el = ensureOverlay();
        const main = el.querySelector(".safety-badge .main");
        const sub  = el.querySelector(".safety-badge .sub");

        const mode    = (payload && payload.mode)    || "NORMAL";
        const message = (payload && payload.message) || "";

        if (mode === "SAFETY_PAUSE") {
            el.classList.add("show", "pause");
            el.classList.remove("emerg");
            main.textContent = "안 전 정 지 모 드";
            sub.textContent  = "잠시 안전을 확인하고 있어요";
        } else if (mode === "EMERGENCY") {
            el.classList.add("show", "emerg");
            el.classList.remove("pause");
            main.textContent = "비 상 정 지 모 드";
            // dashboard가 message에 state 6일 때 'EMERGENCY_STOP' 키워드를 포함시키므로
            // 사용자 안내를 더 친절하게 구분
            if (/EMERGENCY_STOP|E-Stop|빨간불/.test(message)) {
                sub.textContent = "관리자에게 문의해 주세요";
            } else {
                sub.textContent = "관리자가 확인 중입니다";
            }
        } else {
            el.classList.remove("show", "pause", "emerg");
            main.textContent = "";
            sub.textContent  = "";
        }
    }

    async function poll() {
        try {
            const res = await fetch(FIREBASE_URL, { cache: "no-store" });
            const data = await res.json();
            applyMode(data && typeof data === "object" ? data : { mode: "NORMAL" });
        } catch (e) {
            // 네트워크 오류 시 직전 상태 유지 (지속 표시되는 게 안전)
            console.warn("[safety_overlay] poll failed:", e);
        }
    }

    function start() {
        ensureOverlay();
        poll();
        setInterval(poll, 700);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
