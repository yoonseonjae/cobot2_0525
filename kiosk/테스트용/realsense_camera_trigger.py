# [다른 PC] RealSense D435i 전용 통합 미디어 & 트리거 서버
import cv2
import asyncio
import threading
import json
import sys
import base64
import numpy as np
import pyrealsense2 as rs # 🎯 RealSense 핵심 라이브러리 추가
from flask import Flask, Response
import websockets

app = Flask(__name__)

# 1. 📷 [RealSense 세팅] 파이프라인 및 설정
pipeline = rs.pipeline()
config = rs.config()
# D435i의 Color 스트림을 1920x1080, 30fps로 설정
config.enable_stream(rs.stream.color, 1920, 1080, rs.format.bgr8, 30)

# 파이프라인 시작
print("🚀 RealSense D435i 파이프라인을 시작합니다...")
pipeline.start(config)

connected_clients = set()

# 2. 🎬 [영상 스트리밍] RealSense 프레임 제너레이터
def generate_mjpeg_stream():
    while True:
        # 프레임 대기 및 확보
        frames = pipeline.wait_for_frames()
        color_frame = frames.get_color_frame()
        
        if not color_frame:
            continue
            
        # numpy 배열로 변환 (OpenCV 호환)
        frame = np.asanyarray(color_frame.get_data())
        
        # JPEG 압축
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/video_feed')
def video_feed():
    response = Response(generate_mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

def run_flask_server():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, threaded=True)

# 3. 📡 [웹소켓] 클라이언트 핸들러
# [다른 PC] remote_camera_trigger.py 내부 ws_handler 함수만 아래처럼 통째로 교체합니다.

async def ws_handler(websocket):
    client_ip = websocket.remote_address[0]
    print(f"\n✅ [통신 개통] 키오스크 웹 PC({client_ip}) 연결 완료.")
    connected_clients.add(websocket)
    try:
        # 🎯 [핵심] 키오스크가 보내는 메시지를 비동기로 계속 수신 대기하는 루프
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("event") == "start":
                    print(f"\n🤖 [로봇 제어] 키오스크로부터 'start' 트리거 수신!")
                    
                    # TODO: 여기에 실제 로봇 팔 원점 복귀나 하드웨어 예열 코드를 넣으시면 됩니다.
                    print("⚙️ 하드웨어 스탠바이 및 예열 파라미터 세팅 중...")
                    await asyncio.sleep(1.0) # 예열 시간을 시뮬레이션 하는 1초 딜레이
                    
                    # 준비가 끝나면 키오스크로 'ok' 시그널 반환
                    await websocket.send(json.dumps({"event": "ok"}))
                    print(f"✅ [로봇 제어] 하드웨어 준비 완료. 'ok' 시그널 송신 완료!")
            except json.JSONDecodeError:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.remove(websocket)
        print(f"\n❌ [통신 해제] 키오스크 웹 PC({client_ip}) 연결 종료.")

# 4. ⌨️ [입력 트리거] 실시간 RealSense 프레임 나포
async def console_input_loop():
    loop = asyncio.get_running_loop()
    while True:
        await loop.run_in_executor(None, input, "\n📸 캡처 신호 보내기 -> [Enter]를 누르세요!\n")
        
        if connected_clients:
            # 🎯 엔터 입력 시 최신 프레임 1개 즉시 확보
            frames = pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            if color_frame:
                frame = np.asanyarray(color_frame.get_data())
                ret, buffer_frame = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                
                encoded_base64 = base64.b64encode(buffer_frame).decode('utf-8')
                image_data_url = f"data:image/jpeg;base64,{encoded_base64}"
                
                payload = json.dumps({
                    "event": "capture",
                    "image": image_data_url
                })
                await asyncio.gather(*[client.send(payload) for client in connected_clients])
                print("⚡ [RealSense] 맑고 깨끗한 오리지널 프레임 패킷 송신 완료!")
        else:
            print("⚠️ 수신 대기 중인 웹 PC가 없습니다.")

# 5. 🚀 메인 런타임
async def main():
    threading.Thread(target=run_flask_server, daemon=True).start()
    async with websockets.serve(ws_handler, "0.0.0.0", 8765):
        await console_input_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 서버 종료 중...")
    finally:
        pipeline.stop() # 🎯 하드웨어 자원 해제 필수