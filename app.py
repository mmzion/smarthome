import os
import json
import base64
import numpy as np
from flask import Flask, request, jsonify, render_template_string
from groq import Groq
import requests
import io

app = Flask(__name__)

# Groq ক্লায়েন্ট
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

# গ্লোবাল স্টেট এবং বাফারিং (ভয়েস স্ট্রিমের জন্য)
audio_buffer = bytearray()
SILENCE_THRESHOLD = 500  # মাইক্রোফোনের নয়েজ অনুযায়ী অ্যাডজাস্ট করতে পারেন
SILENCE_DURATION_CHUNKS = 15  # প্রায় ১.৫ সেকেন্ড নীরব থাকলে কথা শেষ ধরা হবে
silent_chunks_count = 0
has_speech_started = False
chat_history = []
MAX_HISTORY_LENGTH = 5 
last_voice_reply = "RoomX Audio Engine Active. Waiting for ESP32 stream..."

# ড্যাশবোর্ড টেমপ্লেট
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RoomX | Voice Assistant Hub</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #0f0c29; --purple-main: #9d50bb; --card-bg: rgba(255, 255, 255, 0.05); --text: #f5f5f5; }
        body { font-family: 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }
        .container { width: 95%; max-width: 800px; }
        h1 { color: #ff9f43; text-align: center; margin-bottom: 30px; font-weight: 800; letter-spacing: 2px; }
        .card { background: var(--card-bg); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 20px; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 15px; }
        .relay-card { background: var(--card-bg); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 20px; text-align: center; }
        .relay-card i { font-size: 30px; margin-bottom: 10px; display: block; }
        .relay-card.ON { border-color: #ff9f43; color: #ff9f43; box-shadow: 0 0 15px rgba(255, 159, 67, 0.2); }
        .status-window { background: rgba(0,0,0,0.3); padding: 15px; border-radius: 10px; border-left: 4px solid #ff9f43; font-family: monospace; min-height: 50px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>RoomX AI Hub</h1>
        
        <div class="card">
            <h3>🎙️ Live Audio Engine Log</h3>
            <div class="status-window" id="voice-log">{{ voice_reply }}</div>
        </div>

        <div class="card">
            <h3>Live Status</h3>
            <div id="device-grid" class="grid">Loading Devices...</div>
        </div>
    </div>

    <script>
        function updateUI() {
            fetch('{{ fb_url }}').then(res => res.json()).then(data => {
                const grid = document.getElementById('device-grid');
                grid.innerHTML = '';
                const devices = [
                    { id: "relay_1", name: "Main Light", icon: "fa-lightbulb" },
                    { id: "relay_2", name: "Dim Light", icon: "fa-moon" },
                    { id: "relay_3", name: "Fan", icon: "fa-fan" },
                    { id: "relay_4", name: "Socket", icon: "fa-plug" }
                ];
                devices.forEach(dev => {
                    const state = data[dev.id] || "OFF";
                    grid.innerHTML += `<div class="relay-card ${state}"><i class="fas ${dev.icon} ${state==='ON'&&dev.id==='relay_3'?'fa-spin':''}"></i><span>${dev.name}</span><br><small>${state}</small></div>`;
                });
            });

            fetch('/voice-status').then(res => res.json()).then(stats => {
                document.getElementById('voice-log').innerText = stats.last_reply;
            });
        }
        setInterval(updateUI, 2000);
        updateUI();
    </script>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def home():
    global last_voice_reply
    return render_template_string(DASHBOARD_TEMPLATE, fb_url=FIREBASE_URL, voice_reply=last_voice_reply), 200

@app.route('/voice-status', methods=['GET'])
def voice_status():
    global last_voice_reply
    return jsonify({"last_reply": last_voice_reply})

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global audio_buffer, silent_chunks_count, has_speech_started, last_voice_reply
    
    data = request.get_json() or {}
    audio_base64 = data.get("audio")
    command_text = data.get("text", "").strip()
    
    # চ্যাট ইনপুট ব্যাকআপ হিসেবে চালু রাখা হলো
    if command_text and not audio_base64:
        return process_with_groq(command_text)
        
    # ESP32 থেকে অনবরত আসা অডিও স্ট্রিম হ্যান্ডেল করা
    if audio_base64:
        chunk_bytes = base64.b64decode(audio_base64)
        audio_data = np.frombuffer(chunk_bytes, dtype=np.int16)
        
        if len(audio_data) > 0:
            amplitude = np.max(np.abs(audio_data))
            
            if amplitude > SILENCE_THRESHOLD:
                audio_buffer.extend(chunk_bytes)
                silent_chunks_count = 0
                has_speech_started = True
                last_voice_reply = "🎙️ RoomX is listening... (Capturing Speech)"
            else:
                if has_speech_started:
                    audio_buffer.extend(chunk_bytes)
                    silent_chunks_count += 1
        
        # কথা শেষ হলে জেমিনি/গ্রকের হুইস্পার মডেল কল করা
        if has_speech_started and silent_chunks_count >= SILENCE_DURATION_CHUNKS:
            full_audio = bytes(audio_buffer)
            
            # স্টেট রিসেট
            audio_buffer = bytearray()
            silent_chunks_count = 0
            has_speech_started = False
            
            if len(full_audio) < 20000:  # খুব ছোট নয়েজ হলে ড্রপ
                last_voice_reply = "ℹ️ Ignored short noise."
                return jsonify({"status": "Dropped"}), 200
                
            last_voice_reply = "🧠 Processing Voice via Groq Whisper..."
            return transcribe_and_process(full_audio)
            
        return jsonify({"status": "Streaming", "listening": has_speech_started}), 200

    return jsonify({"error": "No input"}), 400

def transcribe_and_process(audio_bytes):
    global last_voice_reply
    try:
        # র অডিও বাইটকে মেমরি ফাইলে রূপান্তর (Whisper এপিআই এর জন্য WAV ফরম্যাট ডামি হেডার সহ)
        # এখানে ১৬ কিলোহার্টজ, ১৬ বিট, মোনো অডিওর ডামি হেডার জেনারেট করা হচ্ছে
        duration = len(audio_bytes)
        header = bytearray(44)
        header[0:4] = b'RIFF'
        header[4:8] = (duration + 36).to_bytes(4, 'little')
        header[8:12] = b'WAVE'
        header[12:16] = b'fmt '
        header[16:20] = (16).to_bytes(4, 'little')
        header[20:22] = (1).to_bytes(2, 'little')
        header[22:24] = (1).to_bytes(2, 'little')
        header[24:28] = (16000).to_bytes(4, 'little')
        header[28:32] = (32000).to_bytes(4, 'little')
        header[32:34] = (2).to_bytes(2, 'little')
        header[34:36] = (16).to_bytes(2, 'little')
        header[36:40] = b'data'
        header[40:44] = duration.to_bytes(4, 'little')
        
        wav_io = io.BytesIO(header + audio_bytes)
        wav_io.name = "audio.wav"

        # ১. Groq Whisper দিয়ে ভয়েস টু টেক্সট (এটি একদম ইনস্ট্যান্ট হয়)
        transcription = groq_client.audio.transcriptions.create(
            file=wav_io,
            model="whisper-large-v3",
            language="en"
        )
        
        user_text = transcription.text
        print(f"Whisper Transcribed: {user_text}")
        last_voice_reply = f"🗣️ You said: '{user_text}'"
        
        # ২. টেক্সট পাওয়ার পর মূল ল্যামা মডেলে পাঠিয়ে ডিভাইস কন্ট্রোল করা
        return process_with_groq(user_text)
        
    except Exception as e:
        last_voice_reply = f"❌ Whisper Error: {str(e)}"
        return jsonify({"error": str(e)}), 500

def process_with_groq(user_message):
    global chat_history, last_voice_reply
    
    current_relays = {"relay_1": "OFF", "relay_2": "OFF", "relay_3": "OFF", "relay_4": "OFF"}
    try:
        res = requests.get(FIREBASE_URL, timeout=1.5)
        if res.status_code == 200 and res.json(): current_relays = res.json()
    except: pass

    system_instruction = f"""You are RoomX AI, a high-end smart home assistant. 
    Mapping: r1:Main Light, r2:Dim Light, r3:Fan, r4:Socket.
    Current States: {json.dumps(current_relays)}
    Rules: 
    1. Respond in friendly professional tone.
    2. Maintain relay states unless told otherwise.
    3. Return ONLY JSON: {{"reply": "text", "relays": {{"relay_1": "ON/OFF", "relay_2": "ON/OFF", "relay_3": "ON/OFF", "relay_4": "ON/OFF"}}}}"""

    messages = [{"role": "system", "content": system_instruction}]
    for h in chat_history:
        messages.append({"role": "user", "content": h["user"]})
        messages.append({"role": "assistant", "content": h["ai"]})
    messages.append({"role": "user", "content": user_message})

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(completion.choices[0].message.content)
        ai_reply = result.get("reply", "Done.")
        updates = result.get("relays", current_relays)
        
        requests.patch(FIREBASE_URL, json=updates, timeout=1.5)
        
        chat_history.append({"user": user_message, "ai": ai_reply})
        if len(chat_history) > MAX_HISTORY_LENGTH: chat_history.pop(0)
            
        last_voice_reply = f"🤖 RoomX: '{ai_reply}'"
        return jsonify({"status": "Success", "reply": ai_reply}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
