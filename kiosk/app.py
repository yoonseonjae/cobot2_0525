# csg@csg-com:~/doocut_ws/app.py 전체 소스 코드
import os
import datetime
import time
import subprocess
import threading
import requests
import atexit
import cv2
import subprocess
from flask import Flask, render_template, request, jsonify, send_from_directory

app = Flask(__name__)

FIREBASE_START_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/start.json"
FIREBASE_END_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/end.json"
FIREBASE_VOICE_OK_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/voice_ok.json"
FIREBASE_CONCEPT_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/concept.json"
FIREBASE_TOOL_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/tool.json"

IMAGE_DIR = os.path.join(os.getcwd(), 'images')
os.makedirs(IMAGE_DIR, exist_ok=True)

VIDEO_DIR = os.path.join(os.getcwd(), 'video')
os.makedirs(VIDEO_DIR, exist_ok=True)

# csg@csg-com:~/doocut_ws/app.py 에 추가할 내용
import cv2

VIDEO_DIR = os.path.join(os.getcwd(), 'video')
os.makedirs(VIDEO_DIR, exist_ok=True)

SOUND_DIR = os.path.join(os.getcwd(), 'sound')
os.makedirs(SOUND_DIR, exist_ok=True)

# csg@csg-com:~/doocut_ws/app.py 수정본
@app.route('/save_video', methods=['POST'])
def save_video():
    if 'video' not in request.files:
        print("❌ [에러] 파일이 전송되지 않음")
        return jsonify({"status": "error", "message": "파일 없음"}), 400

    video_file = request.files['video']
    temp_path = os.path.join(VIDEO_DIR, f"temp_{int(time.time())}.webm")
    final_path = os.path.join(VIDEO_DIR, f"timelapse_{int(time.time())}.mp4")
    
    # 파일을 일단 저장
    video_file.save(temp_path)
    print(f"✅ [저장] 임시 영상 저장 완료: {temp_path} ({os.path.getsize(temp_path)} bytes)")

    try:
        # 🎯 FFmpeg 명령어 설명
        # -i: 입력 파일
        # -filter_complex "[0:v]setpts=0.33*PTS[v]": 영상 속도를 3배속(1/3배 시간)으로
        # -map "[v]": 비디오 스트림만 추출
        # -y: 덮어쓰기
        cmd = [
            'ffmpeg', '-y', '-i', temp_path,
            '-filter_complex', '[0:v]setpts=0.333333*(PTS-STARTPTS)[v]',
            '-map', '[v]', '-c:v', 'libx264', '-crf', '23', '-preset', 'veryfast',
            '-r', '30',
            final_path
        ]
        
        # 명령어 실행
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"🎉 [인코딩 완료] 3배속 영상 생성 성공: {final_path}")
            if os.path.exists(temp_path): os.remove(temp_path)
            return jsonify({"status": "success", "file": f"/video/{os.path.basename(final_path)}"})
        else:
            print(f"❌ [FFmpeg 에러]: {result.stderr}")
            return jsonify({"status": "error", "message": "인코딩 실패"}), 500

    except Exception as e:
        print(f"❌ [에러]: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def reset_all_firebase_flags():
    """ 프로세스 종료 감지 시 클라우드 저장소 마스터 클리어 연산 """
    try:
        requests.put(FIREBASE_START_URL, json=False, timeout=2)
        requests.put(FIREBASE_END_URL, json=False, timeout=2)
        requests.put(FIREBASE_VOICE_OK_URL, json=False, timeout=2)
        requests.put(FIREBASE_CONCEPT_URL, json="", timeout=2)
        requests.put(FIREBASE_TOOL_URL, json={
            "black": False,
            "crown": False,
            "gun": False,
            "hat": False,
            "pink": False,
            "wand": False
        }, timeout=2)
        requests.put("https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/capture.json", json=False, timeout=2)
        print("🛑 [페일세이프 가동] 클라우드 플래그(/start, /end, /voice_ok, /concept, /tool, /capture)가 모두 리셋되었습니다.")
    except Exception as e:
        print(f"⚠️ Firebase 백엔드 강제 청소 실패 예외: {e}")

def open_browser_kiosk():
    time.sleep(2) 
    target_url = "http://localhost:5000"
    
    # 🎯 [NEW] Firefox 자동 재생(Autoplay) 허용 프로필 생성
    profile_dir = os.path.join(os.getcwd(), 'firefox_profile')
    os.makedirs(profile_dir, exist_ok=True)
    prefs_js_path = os.path.join(profile_dir, 'prefs.js')
    with open(prefs_js_path, 'w') as f:
        f.write('user_pref("media.autoplay.default", 0);\n')
        f.write('user_pref("media.autoplay.allow-extension-background-pages", true);\n')
        f.write('user_pref("media.autoplay.block-event.enabled", false);\n')

    command = ['firefox', '--profile', profile_dir, '--kiosk', target_url]
    try:
        proc = subprocess.Popen(command)
        print(f"🚀 [키오스크 모드] Firefox 키오스크가 {target_url}로 성공적으로 구동되었습니다.")
        proc.wait() 
        print("\n💥 [경고] 브라우저 창 강제 종료 포착! 프로세스 락 풀림과 동시에 중앙 리셋 엔진을 기동합니다.")
        reset_all_firebase_flags()
    except FileNotFoundError:
        print("⚠️ [에러] Firefox 브라우저 바이너리 경로 이상")

def cleanup_on_exit():
    print("\n🛑 [백엔드 가동중단] app.py 서버 셧다운 감지. 최종 클라우드 리셋을 단행합니다.")
    reset_all_firebase_flags()

atexit.register(cleanup_on_exit)

@app.context_processor
def inject_local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.254.254.254', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return dict(local_ip=ip)

@app.route('/')
def index(): return render_template('index.html')

@app.route('/frame')
def frame(): return render_template('frame.html')

@app.route('/voice')
def voice(): return render_template('voice.html')

@app.route('/camera')
def camera(): return render_template('camera.html')

@app.route('/result')
def result(): return render_template('last.html')

@app.route('/images/<filename>')
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route('/video/<filename>')
def serve_video(filename):
    return send_from_directory(VIDEO_DIR, filename)

@app.route('/sound/<path:filename>')
def serve_sound(filename):
    return send_from_directory(SOUND_DIR, filename)

@app.route('/save_capture', methods=['POST'])
def save_capture():
    data = request.json
    image_data_string = data.get('image')
    if not image_data_string: return jsonify({"status": "error"}), 400
    try:
        import base64, datetime
        import numpy as np
        header, encoded_body = image_data_string.split(",", 1)
        decoded_binary = base64.b64decode(encoded_body)
        
        # 1. 뷰티 필터 적용 (OpenCV)
        nparr = np.frombuffer(decoded_binary, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # 피부 보정: Bilateral Filter (경계는 유지하고 피부 질감은 부드럽게)
        smooth = cv2.bilateralFilter(img, 15, 45, 45)
        
        # 톤업 & 화사함: 밝기와 대비 살짝 증가
        beauty_img = cv2.convertScaleAbs(smooth, alpha=1.1, beta=15)
        
        # 다시 base64로 인코딩 (프론트엔드 반환용 및 저장용)
        _, buffer = cv2.imencode('.jpg', beauty_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        filtered_binary = buffer.tobytes()
        filtered_base64 = "data:image/jpeg;base64," + base64.b64encode(filtered_binary).decode('utf-8')
        
        # 파일로 저장
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        file_name = f"captured_{timestamp}.jpg"
        file_path = os.path.join(IMAGE_DIR, file_name)
        with open(file_path, "wb") as f: f.write(filtered_binary)
        
        return jsonify({"status": "success", "saved_file": f"/images/{file_name}", "filtered_image": filtered_base64})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/save_strip', methods=['POST'])
def save_strip():
    data = request.json
    image_data_string = data.get('image')
    if not image_data_string: return jsonify({"status": "error"}), 400
    try:
        import base64, datetime
        header, encoded_body = image_data_string.split(",", 1)
        decoded_binary = base64.b64decode(encoded_body)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"final_strip_{timestamp}.jpg"
        file_path = os.path.join(IMAGE_DIR, file_name)
        with open(file_path, "wb") as f: f.write(decoded_binary)
        return jsonify({"status": "success", "saved_file": f"/images/{file_name}"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    threading.Thread(target=open_browser_kiosk, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)