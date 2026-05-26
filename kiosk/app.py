# app.py 전체 소스 코드 (코드 리뷰 대비 상세 주석 포함)
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

# [구현 내용] Firebase 실시간 데이터베이스(RTDB) URL 설정
# 로봇과의 상태 동기화를 위해 사용되는 각 플래그의 엔드포인트 주소입니다.
FIREBASE_START_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/start.json"
FIREBASE_END_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/end.json"
FIREBASE_VOICE_OK_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/voice_ok.json"
FIREBASE_CONCEPT_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/concept.json"
FIREBASE_TOOL_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/tool.json"

# [구현 내용] 이미지, 비디오, 사운드 파일이 저장될 로컬 디렉토리 생성 로직
# 앱 시작 시 폴더가 없으면 자동으로 생성(exist_ok=True)하여 파일 저장 시 에러를 방지합니다.
IMAGE_DIR = os.path.join(os.getcwd(), 'images')
os.makedirs(IMAGE_DIR, exist_ok=True)

VIDEO_DIR = os.path.join(os.getcwd(), 'video')
os.makedirs(VIDEO_DIR, exist_ok=True)

SOUND_DIR = os.path.join(os.getcwd(), 'sound')
os.makedirs(SOUND_DIR, exist_ok=True)


# [API 라우트] 타임랩스 비디오 저장 및 인코딩 처리
@app.route('/save_video', methods=['POST'])
def save_video():
    """
    [구현 내용] 프론트엔드(MediaRecorder)에서 녹화된 원본 WebM 영상을 받아 
    FFmpeg를 통해 3배속 H.264 MP4로 변환하여 저장하는 백엔드 로직입니다.
    """
    if 'video' not in request.files:
        print("❌ [에러] 파일이 전송되지 않음")
        return jsonify({"status": "error", "message": "파일 없음"}), 400

    video_file = request.files['video']
    temp_path = os.path.join(VIDEO_DIR, f"temp_{int(time.time())}.webm")
    final_path = os.path.join(VIDEO_DIR, f"timelapse_{int(time.time())}.mp4")
    
    # 1. 스트리밍으로 넘어온 대용량 영상 파일을 임시 경로에 우선 저장합니다.
    video_file.save(temp_path)
    print(f"✅ [저장] 임시 영상 저장 완료: {temp_path} ({os.path.getsize(temp_path)} bytes)")

    try:
        # 2. FFmpeg 자식 프로세스 호출 (Subprocess)
        # [FFmpeg 옵션 설명]
        # -i: 입력 파일 경로
        # -filter_complex "[0:v]setpts=0.333333*(PTS-STARTPTS)[v]": 비디오 프레임의 타임스탬프(PTS)를 1/3로 줄여서 3배속 재생 효과 구현
        # -map "[v]": 오디오를 제외하고 비디오 스트림만 추출 (타임랩스 목적)
        # -c:v libx264: H.264 코덱으로 인코딩하여 모바일 웹 호환성 확보
        # -crf 23 -preset veryfast: 용량 대비 화질 비율(23) 및 인코딩 속도 최적화
        cmd = [
            'ffmpeg', '-y', '-i', temp_path,
            '-filter_complex', '[0:v]setpts=0.333333*(PTS-STARTPTS)[v]',
            '-map', '[v]', '-c:v', 'libx264', '-crf', '23', '-preset', 'veryfast',
            '-r', '30',
            final_path
        ]
        
        # subprocess.run을 통해 동기적으로 명령어 실행 후 결과 대기
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"🎉 [인코딩 완료] 3배속 영상 생성 성공: {final_path}")
            if os.path.exists(temp_path): os.remove(temp_path) # 성공 시 임시 WebM 파일 삭제
            return jsonify({"status": "success", "file": f"/video/{os.path.basename(final_path)}"})
        else:
            print(f"❌ [FFmpeg 에러]: {result.stderr}")
            return jsonify({"status": "error", "message": "인코딩 실패"}), 500

    except Exception as e:
        print(f"❌ [에러]: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def reset_all_firebase_flags():
    """
    [구현 내용] 프로그램 강제 종료나 재시작 시, 로봇이 이전 상태(ex. 캡처 중, 촬영 중)에 
    갇혀 오작동하는 것을 막기 위해 모든 Firebase DB 상태를 초기화(False/빈값)하는 안전 장치입니다.
    """
    try:
        requests.put(FIREBASE_START_URL, json=False, timeout=2)
        requests.put(FIREBASE_END_URL, json=False, timeout=2)
        requests.put(FIREBASE_VOICE_OK_URL, json=False, timeout=2)
        requests.put(FIREBASE_CONCEPT_URL, json="", timeout=2)
        requests.put(FIREBASE_TOOL_URL, json={
            "black": False, "crown": False, "gun": False,
            "hat": False, "pink": False, "wand": False
        }, timeout=2)
        requests.put("https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/capture.json", json=False, timeout=2)
        print("🛑 [페일세이프 가동] 클라우드 플래그가 모두 리셋되었습니다.")
    except Exception as e:
        print(f"⚠️ Firebase 백엔드 강제 청소 실패 예외: {e}")

def open_browser_kiosk():
    """
    [구현 내용] 백엔드 서버가 켜질 때 자동으로 Firefox를 '키오스크(전체화면) 모드'로 실행시키는 스레드입니다.
    자동 재생 정책(Autoplay block)을 우회하기 위해 사용자 프로필(prefs.js)을 동적으로 생성하여 주입합니다.
    """
    time.sleep(2) # 서버가 완전히 뜰 때까지 2초 대기
    target_url = "http://localhost:5000"
    
    profile_dir = os.path.join(os.getcwd(), 'firefox_profile')
    os.makedirs(profile_dir, exist_ok=True)
    prefs_js_path = os.path.join(profile_dir, 'prefs.js')
    with open(prefs_js_path, 'w') as f:
        f.write('user_pref("media.autoplay.default", 0);\n') # 미디어 자동 재생 허용
        f.write('user_pref("media.autoplay.allow-extension-background-pages", true);\n')
        f.write('user_pref("media.autoplay.block-event.enabled", false);\n')

    command = ['firefox', '--new-instance', '--profile', profile_dir, '--kiosk', target_url]
    try:
        proc = subprocess.Popen(command)
        print(f"🚀 [키오스크 모드] Firefox 키오스크가 구동되었습니다.")
        proc.wait() 
        print("\n💥 [경고] 브라우저 창 강제 종료 포착! 리셋 엔진을 기동합니다.")
        reset_all_firebase_flags()
    except FileNotFoundError:
        print("⚠️ [에러] Firefox 브라우저 바이너리 경로 이상")

def cleanup_on_exit():
    """ 프로세스 종료 시그널(Ctrl+C 등) 수신 시 리셋 함수 호출 """
    print("\n🛑 [백엔드 가동중단] app.py 서버 셧다운 감지. 최종 클라우드 리셋을 단행합니다.")
    reset_all_firebase_flags()

atexit.register(cleanup_on_exit) # 프로그램 종료 시 cleanup_on_exit 실행 등록

@app.context_processor
def inject_local_ip():
    """ [구현 내용] QR 코드 생성 시 외부 접속 가능한 로컬 IP 주소를 템플릿에 주입하기 위한 함수 """
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

# ==========================================
# 라우팅 (페이지 및 정적 파일 제공)
# ==========================================
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
def serve_image(filename): return send_from_directory(IMAGE_DIR, filename)

@app.route('/video/<filename>')
def serve_video(filename): return send_from_directory(VIDEO_DIR, filename)

@app.route('/sound/<path:filename>')
def serve_sound(filename): return send_from_directory(SOUND_DIR, filename)


# [API 라우트] 촬영된 사진(Base64) 수신 및 OpenCV 뷰티 필터 적용 후 저장
@app.route('/save_capture', methods=['POST'])
def save_capture():
    """
    [구현 내용] 프론트엔드에서 넘어온 Base64 캔버스 이미지를 파이썬 배열로 디코딩하고, 
    OpenCV를 통해 피부 보정(Bilateral Filter) 및 톤업 처리를 수행하여 뽀샤시한 결과물을 반환합니다.
    """
    data = request.json
    image_data_string = data.get('image')
    if not image_data_string: return jsonify({"status": "error"}), 400
    try:
        import base64, datetime
        import numpy as np
        
        # 1. Base64 헤더 제거 및 디코딩
        header, encoded_body = image_data_string.split(",", 1)
        decoded_binary = base64.b64decode(encoded_body)
        
        # 2. 바이너리 데이터를 OpenCV Numpy 배열로 변환
        nparr = np.frombuffer(decoded_binary, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # 3. [뷰티 필터 엔진] 
        # cv2.bilateralFilter: 가우시안 블러와 달리 엣지(윤곽선)는 보존하면서 질감만 뭉개어 부드러운 피부를 표현합니다.
        smooth = cv2.bilateralFilter(img, 15, 45, 45)
        
        # 4. 톤업 & 화사함: convertScaleAbs를 통해 알파(대비)를 1.1배, 베타(밝기)를 15만큼 올려 밝게 만듭니다.
        beauty_img = cv2.convertScaleAbs(smooth, alpha=1.1, beta=15)
        
        # 5. 프론트엔드로 즉시 렌더링하기 위해 처리된 이미지를 다시 Base64 문자열로 인코딩합니다.
        _, buffer = cv2.imencode('.jpg', beauty_img, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        filtered_binary = buffer.tobytes()
        filtered_base64 = "data:image/jpeg;base64," + base64.b64encode(filtered_binary).decode('utf-8')
        
        # 서버 디스크에도 원본 사진으로 저장
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        file_name = f"captured_{timestamp}.jpg"
        file_path = os.path.join(IMAGE_DIR, file_name)
        with open(file_path, "wb") as f: f.write(filtered_binary)
        
        return jsonify({"status": "success", "saved_file": f"/images/{file_name}", "filtered_image": filtered_base64})
    except Exception as e: 
        return jsonify({"status": "error", "message": str(e)}), 500

# [API 라우트] 완성된 네컷 사진(스트립) 저장 (QR코드 용)
@app.route('/save_strip', methods=['POST'])
def save_strip():
    """
    [구현 내용] html2canvas로 만들어진 최종 네컷 프레임(결과물)을 받아 서버에 이미지로 저장합니다. 
    이 경로는 QR코드에 담겨 사용자가 모바일로 다운로드할 수 있게 됩니다.
    """
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
    except Exception as e: 
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Flask 서버와 동시에 키오스크 브라우저 데몬 스레드 구동
    threading.Thread(target=open_browser_kiosk, daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)