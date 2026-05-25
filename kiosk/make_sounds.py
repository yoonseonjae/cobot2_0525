import os
import urllib.request
import subprocess

sounds_dir = "static/sounds"
os.makedirs(sounds_dir, exist_ok=True)

# 1. Download TTS for 3, 2, 1
texts = {"3": "삼", "2": "이", "1": "일"}
for num, text in texts.items():
    url = f"https://translate.google.com/translate_tts?ie=UTF-8&client=tw-ob&tl=ko&q={urllib.parse.quote(text)}"
    raw_path = os.path.join(sounds_dir, f"raw_{num}.mp3")
    urllib.request.urlretrieve(url, raw_path)
    
    # Apply enhanced robot filter with ffmpeg
    # Pitch down slightly, add fast tremolo for mechanical stutter, echo and volume boost
    out_path = os.path.join(sounds_dir, f"robot_{num}.mp3")
    cmd = [
        "ffmpeg", "-y", "-i", raw_path,
        "-filter_complex", "asetrate=44100*0.85,aresample=44100,tremolo=f=45:d=0.9,echo=0.8:0.8:10:0.4,volume=2.5",
        out_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"Generated {out_path}")
    if os.path.exists(raw_path):
        os.remove(raw_path)

# 2. Synthesize a punchy camera shutter sound using ffmpeg lavfi
shutter_path = os.path.join(sounds_dir, "shutter.mp3")
shutter_cmd = [
    "ffmpeg", "-y", 
    "-f", "lavfi", "-i", "anoisesrc=c=pink:r=44100:a=1.0", 
    "-f", "lavfi", "-i", "sine=f=120:r=44100:d=0.2", 
    "-filter_complex", 
    "[0:a]asplit[n1][n2]; [n1]afade=t=out:st=0:d=0.03:curve=exp[out1]; [n2]afade=t=out:st=0:d=0.04:curve=exp,adelay=60|60[out2]; [1:a]afade=t=out:st=0:d=0.02,volume=0.8[click1]; [1:a]afade=t=out:st=0:d=0.03,volume=0.6,adelay=60|60[click2]; [out1][out2][click1][click2]amix=inputs=4:duration=first,compand=attacks=0:points=-80/-80|-20/-20|0/-3|20/-3,bass=g=15:f=110,treble=g=5:f=8000,volume=3.0[final]", 
    "-map", "[final]", "-t", "0.2", 
    shutter_path
]
subprocess.run(shutter_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(f"Generated {shutter_path} (Punchy Synthesized Shutter)")

print("✅ All sound effects ready!")
