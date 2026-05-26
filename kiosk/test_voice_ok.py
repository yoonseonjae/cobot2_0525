import time
import requests
import sys

# Firebase Realtime Database voice_ok URL
URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/voice_ok.json"

def set_voice_ok(value):
    try:
        response = requests.put(URL, json=value, timeout=5)
        if response.status_code == 200:
            print(f"✅ Firebase /voice_ok -> {value} 성공")
        else:
            print(f"❌ 설정 실패 (상태 코드: {response.status_code})")
    except Exception as e:
        print(f"❌ Firebase 통신 에러: {e}")

if __name__ == "__main__":
    print("🚀 스크립트 실행: /voice_ok를 true로 설정합니다.")
    set_voice_ok(True)
    
    print("\n[알림] 대기 중... 종료하려면 Ctrl + C 키를 누르세요.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n\n🛑 종료 감지: /voice_ok를 false로 되돌립니다.")
        set_voice_ok(False)
        print("👋 프로그램이 안전하게 종료되었습니다.")
        sys.exit(0)
