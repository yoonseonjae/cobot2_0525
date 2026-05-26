import time
import requests

BASE_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/"

def update_db(path, data):
    url = f"{BASE_URL}{path}.json"
    try:
        res = requests.put(url, json=data, timeout=5)
        if res.status_code == 200:
            print(f"✅ {path} -> {data} 성공")
        else:
            print(f"❌ {path} 실패: {res.status_code}")
    except Exception as e:
        print(f"❌ {path} 에러: {e}")

if __name__ == "__main__":
    print("🎂 [생일 컨셉 시뮬레이터] 3초 후에 시작합니다...")
    time.sleep(3)
    
    # 1. 컨셉 선택
    print("\n🎤 사용자가 '생일 축하해'라고 말했습니다. 컨셉을 birthday로 설정합니다.")
    update_db("concept", "birthday")
    
    # 2. 첫 번째 소품 (꼬깔모자 - hat) 전달
    time.sleep(3)
    print("\n🎁 로봇이 '생일 꼬깔모자(hat)'를 가져와서 전달 중입니다...")
    update_db("tool/hat", True)
    
    # 3. 두 번째 소품 (핑크 소품 - pink) 전달
    time.sleep(3)
    print("\n🎁 로봇이 '핑크 소품(pink)'을 가져와서 전달 중입니다...")
    update_db("tool/pink", True)
    
    # 4. 최종 준비 완료 및 촬영 이동 (voice_ok -> True)
    time.sleep(3)
    print("\n🎉 모든 소품이 완벽히 수거되었습니다. 촬영 위치로 이동하며 voice_ok를 활성화합니다.")
    update_db("voice_ok", True)
    
    print("\n👋 시뮬레이터 완료!")
