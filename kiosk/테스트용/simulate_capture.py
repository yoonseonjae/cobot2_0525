import time
import requests

BASE_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/"

def set_capture(value):
    url = f"{BASE_URL}capture.json"
    try:
        res = requests.put(url, json=value, timeout=5)
        if res.status_code == 200:
            print(f"✅ capture -> {value} 성공")
        else:
            print(f"❌ capture 실패: {res.status_code}")
    except Exception as e:
        print(f"❌ capture 에러: {e}")

if __name__ == "__main__":
    print("📸 [사진 촬영 시뮬레이터]")
    print("엔터 키를 누를 때마다 화면 캡처 신호(true)를 보내고, 1초 뒤 자동 해제(false)됩니다.")
    print("종료하려면 Ctrl+C 를 누르세요.\n")
    
    count = 1
    try:
        while True:
            input(f"👉 [{count}번째 사진] 엔터를 누르면 찰칵! 📸")
            
            # 1. 캡처 신호 전송
            set_capture(True)
            
            # 2. 1초 대기 후 초기화
            time.sleep(1)
            set_capture(False)
            
            print("🔄 다음 촬영 준비 완료\n")
            count += 1
    except KeyboardInterrupt:
        print("\n👋 시뮬레이터 종료! capture 플래그를 false로 원상복구합니다.")
        set_capture(False)
