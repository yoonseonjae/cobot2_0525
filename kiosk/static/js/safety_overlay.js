// safety_overlay.js
// Firebase에서 /safety_mode.json 을 주기적으로 확인하여 전체 화면에 오버레이를 띄웁니다.

const FIREBASE_SAFETY_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/safety_mode.json";

document.addEventListener("DOMContentLoaded", () => {
    // 오버레이 컨테이너 생성
    const overlay = document.createElement("div");
    overlay.id = "safetyGlobalOverlay";
    overlay.style.position = "fixed";
    overlay.style.top = "0";
    overlay.style.left = "0";
    overlay.style.width = "100%";
    overlay.style.height = "100%";
    overlay.style.zIndex = "9999";
    overlay.style.display = "none";
    overlay.style.flexDirection = "column";
    overlay.style.justifyContent = "center";
    overlay.style.alignItems = "center";
    overlay.style.transition = "all 0.3s ease-in-out";
    overlay.style.pointerEvents = "all"; // 이벤트를 가로채서 아무것도 못 누르게 함

    const title = document.createElement("h1");
    title.style.fontSize = "4rem";
    title.style.fontWeight = "bold";
    title.style.marginBottom = "1rem";
    title.style.textShadow = "0 4px 10px rgba(0,0,0,0.5)";

    const msg = document.createElement("p");
    msg.style.fontSize = "2rem";
    msg.style.textAlign = "center";
    msg.style.textShadow = "0 2px 5px rgba(0,0,0,0.5)";

    overlay.appendChild(title);
    overlay.appendChild(msg);
    document.body.appendChild(overlay);

    let lastMode = "NORMAL";

    setInterval(async () => {
        try {
            const response = await fetch(FIREBASE_SAFETY_URL);
            const data = await response.json();
            if (!data) return;

            const mode = data.mode || "NORMAL";
            
            if (mode !== lastMode) {
                lastMode = mode;
                if (mode === "NORMAL") {
                    overlay.style.display = "none";
                } else if (mode === "SAFETY_PAUSE") {
                    overlay.style.display = "flex";
                    overlay.style.backgroundColor = "rgba(255, 193, 7, 0.85)"; // Yellow/Warning
                    overlay.style.color = "#000";
                    overlay.style.boxShadow = "inset 0 0 50px rgba(255, 152, 0, 1)";
                    title.innerText = "일시 정지";
                    msg.innerHTML = "안전을 위해 로봇이 일시 정지되었습니다.<br>관리자가 확인 후 재개합니다.";
                } else if (mode === "EMERGENCY") {
                    overlay.style.display = "flex";
                    overlay.style.backgroundColor = "rgba(244, 67, 54, 0.9)"; // Red/Emergency
                    overlay.style.color = "#FFF";
                    // Pulsing outline effect via keyframes in css or box-shadow
                    overlay.style.boxShadow = "inset 0 0 100px rgba(183, 28, 28, 1)";
                    title.innerText = "비상 정지";
                    msg.innerHTML = "긴급 상황이 발생하여 로봇이 정지되었습니다.<br>관리자를 호출해 주세요.";
                }
            }
        } catch (err) {
            console.error("Safety Mode Fetch Error:", err);
        }
    }, 500); // 0.5초 주기 폴링
});
