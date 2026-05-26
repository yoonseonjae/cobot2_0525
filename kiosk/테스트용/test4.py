# [다른 PC] 통합 미디어 & 트리거 서버 (remote_camera_trigger.py)
import cv2
import asyncio
import threading
import json
import sys
from flask import Flask, Response
import websockets
import base64

app = Flask(__name__)

# 1. 📷 [카메라 세팅] OpenCV 웹캠 객체 초기화 (외장 카메라면 1 또는 2로 변경)
camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

# 웹소켓 클라이언트들을 담아둘 메모리 파라미터
connected_clients = set()

# 2. 🎬 [영상 스트리밍] MJPEG 프레임 제너레이터 함수
def generate_mjpeg_stream():
    while True:
        success, frame = camera.read()
        if not success:
            break
        else:
            # 프레임을 JPEG 바이너리 파라미터로 압축 인코딩
            ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

# 🎯 [중요] Flask 영상 라우트 및 CORS 보안 해제 파라미터 주입
@app.route('/video_feed')
def video_feed():
    response = Response(generate_mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')
    # 웹 PC가 캔버스를 캡처할 때 SecurityError(Tainted Canvas)가 뜨는 것을 완벽 차단!
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

# Flask 서버를 백그라운드 스레드에서 구동하기 위한 래퍼 함수
def run_flask_server():
    # threaded=True 파라미터로 다중 접속 허용
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

# 3. 📡 [웹소켓] 클라이언트 접속 제어 핸들러
async def ws_handler(websocket):
    client_ip = websocket.remote_address[0]
    print(f"\n✅ [통신 개통] 웹 PC({client_ip})가 소켓 채널에 세련되게 안착했습니다.")
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.remove(websocket)
        print(f"\n❌ [통신 해제] 웹 PC({client_ip}) 연결 종료.")

# 4. ⌨️ [입력 트리거] 터미널 엔터키 감지 및 브로드캐스팅 비동기 루프
async def console_input_loop():
    loop = asyncio.get_running_loop()
    while True:
        # 터미널 엔터 입력 대기
        await loop.run_in_executor(None, input, "\n📸 캡처 신호 보내기 -> 터미널에서 [Enter] 키를 누르세요!\n")
        
        if connected_clients:
            # 🎯 엔터 인터럽트가 발생한 바로 그 순간, 카메라 원본 프레임 나포!
            success, frame = camera.read()
            if success:
                # 고화질 JPEG 파일 바이너리로 압축 인코딩 (buffer_frame 매개변수 생성)
                ret, buffer_frame = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                
                # 이진 데이터를 웹 표준 아스키 스트링으로 직렬화 (encoded_base64 파라미터 셋업)
                encoded_base64 = base64.b64encode(buffer_frame).decode('utf-8')
                image_data_url = f"data:image/jpeg;base64,{encoded_base64}"
                
                # 🎯 [교정 완료] 예외를 일으키던 미선언 변수 라인을 완벽히 걷어내고 clean 패킷 파라미터 빌드
                payload = json.dumps({
                    "event": "capture",
                    "image": image_data_url
                })
                
                await asyncio.gather(*[client.send(payload) for client in connected_clients])
                print("⚡ [직렬화 완료] 맑고 깨끗한 오리지널 프레임 패킷이 웹 PC로 송신되었습니다!")
            else:
                print("❌ [카메라 에러] 프레임을 읽어오지 못했습니다.")
        else:
            print("⚠️ 수신 대기 중인 웹 PC가 없습니다. (웹 노트북에서 페이지를 먼저 켜주세요)")

# 5. 🚀 [메인 런타임] 시스템 통합 가동
async def main():
    print("==================================================")
    print(" 🖤 인생두컷 통합 미디어 & 트리거 서버 가동")
    print(" 🖤 [영상 송출] Port 5000 가동 중...")
    print(" 🖤 [신호 송출] Port 8765 가동 중...")
    print("==================================================")
    
    # 영상 스트리밍(Flask)은 데몬 스레드로 분리하여 비동기 루프와 격리
    threading.Thread(target=run_flask_server, daemon=True).start()
    
    # 웹소켓 서버를 8765 포트로 개방하고, 터미널 입력 루프로 진입
    async with websockets.serve(ws_handler, "0.0.0.0", 8765):
        await console_input_loop()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 통합 서버가 안전하게 종료되었습니다.")