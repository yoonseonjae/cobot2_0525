# [다른 PC 구동용] csg@csg-com:~/robot_ws/trigger_server.py
import asyncio
import json
import threading
import websockets
from pynput import keyboard

# 🎯 [파라미터] 연결된 웹 PC 브라우저 인스턴스를 보관할 세트 자료구조
connected_clients = set()
main_loop = None # 비동기 컨텍스트 스레드 브릿지를 위한 글로벌 루프 변수

# 웹소켓 클라이언트 커넥션 수립/해제 제어 파라미터 함수
async def register_client(websocket):
    connected_clients.add(websocket)
    print("📡 [통신 개통] 웹 노트북의 브라우저가 트리거 라인에 정상 입각했습니다.")
    try:
        # 클라이언트가 소켓 링크를 끊을 때까지 비동기 차단 대기
        await websocket.wait_closed()
    finally:
        connected_clients.remove(websocket)
        print("🔌 [통신 해제] 웹 노트북과의 소켓 커넥션이 안전하게 종료되었습니다.")

# 🎯 [파라미터] 스페이스바 입력 시 "capture" 패킷을 웹 PC로 쏘아보내는 비동기 함수
async def broadcast_capture_signal():
    if connected_clients:
        # 송신할 메시지 페이로드 파라미터 정의 및 JSON 직렬화
        payload_data = {"event": "capture"}
        serialized_payload = json.dumps(payload_data)
        
        # 연결된 모든 브라우저에 마이크로초 단위로 동시 패킷 발송
        await asyncio.gather(*[client.send(serialized_payload) for client in connected_clients])
        print("⚡ [트리거 완료] 'capture' 신호가 웹 PC 스크린으로 거침없이 송신되었습니다.")
    else:
        print("⚠️  [송신 실패] 현재 연결된 웹 PC 브라우저 클라이언트가 존재하지 않습니다.")

# 🎯 [파라미터] OS 레벨 키보드 인터럽트 콜백 함수
def on_key_press(key):
    try:
        # 타겟 버튼 파라미터가 스페이스바 플래그와 일치하는지 검사
        if key == keyboard.Key.space:
            if main_loop and main_loop.is_running():
                # 별도 스레드 영역에서 메인 비동기 루프 공간으로 안전하게 작업 파라미터 주입
                asyncio.run_coroutine_threadsafe(broadcast_capture_signal(), main_loop)
    except Exception as exception_log:
        print(f"키보드 인터럽트 파라미터 처리 중 예외 발생: {exception_log}")

# 백그라운드 스레드에서 무한 루프로 돌아갈 키보드 리스너 가동 파라미터
def run_global_keyboard_listener():
    with keyboard.Listener(on_press=on_key_press) as listener_instance:
        listener_instance.join()

async def main():
    global main_loop
    main_loop = asyncio.get_running_loop()
    
    # OS 커널 키보드 감시용 전역 스레드 분리 가동
    threading.Thread(target=run_global_keyboard_listener, daemon=True).start()
    
    # 🎯 [파라미터 주입] 모든 IP 대역(0.0.0.0)과 고유 포트(8765) 채널 바인딩 개방
    async with websockets.serve(register_client, "0.0.0.0", 8765):
        print("=========================================================")
        print(" 🖤 인생두컷 [독립형 capture 트리거 서버] 가동 시작")
        print(" 🖤 청정 통신 포트 채널 바인딩: 8765")
        print(" 🖤 건너편 PC 물리 키보드의 [스페이스바]를 누르면 신호가 전송됩니다.")
        print("=========================================================")
        await asyncio.Future() # 영구 생존 대기

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 트리거 서버가 세련되게 종료되었습니다.")