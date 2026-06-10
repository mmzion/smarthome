import os
import json
import base64
import time
import numpy as np
from flask import Flask, request, jsonify, render_template_string
from groq import Groq
import requests
import io

app = Flask(__name__)

# Groq Config
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

# Global States
audio_buffer = bytearray()
SILENCE_THRESHOLD = 600  
SILENCE_DURATION_CHUNKS = 10  
silent_chunks_count = 0
has_speech_started = False

# Chat & Connection Tracking
chat_history = []
MAX_HISTORY_LENGTH = 5 
last_esp32_seen = 0  

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RoomX | Unified Intelligence Hub</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --bg: #0f0c29;
            --purple-main: #9d50bb;
            --card-bg: rgba(255, 255, 255, 0.05);
            --text: #f5f5f5;
            --green-glow: #00ff87;
        }

        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { 
            font-family: 'Segoe UI', sans-serif; 
            background: var(--bg); 
            background-image: radial-gradient(circle at 50% 50%, #1a1a3a 0%, #0f0c29 100%);
            color: var(--text); 
            margin: 0; padding: 0;
            display: flex; flex-direction: column; align-items: center; min-height: 100vh;
        }

        header {
            width: 100%; padding: 20px; text-align: center;
            background: rgba(0,0,0,0.3); backdrop-filter: blur(10px);
            border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px;
            display: flex; justify-content: center; align-items: center; gap: 15px;
        }
        header h1 { margin: 0; font-size: 28px; letter-spacing: 2px; font-weight: 800; color: #fff; }
        
        .conn-badge {
            background: rgba(0,0,0,0.4); border: 1px solid #ff2e63; color: #ff2e63;
            padding: 6px 14px; border-radius: 50px; font-size: 12px; font-weight: 600;
            display: flex; align-items: center; gap: 8px; transition: 0.3s;
        }
        .conn-badge.online {
            border-color: var(--green-glow); color: var(--green-glow);
            box-shadow: 0 0 10px rgba(0, 255, 135, 0.2);
        }
        .conn-badge i { font-size: 10px; }

        .container { width: 95%; max-width: 900px; display: flex; flex-direction: column; gap: 20px; padding-bottom: 40px; }

        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 15px; width: 100%; }
        .relay-card { 
            background: var(--card-bg); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; 
            padding: 20px; text-align: center; transition: all 0.3s ease;
        }
        .relay-card i { font-size: 30px; margin-bottom: 10px; display: block; }
        .relay-card span { font-size: 14px; font-weight: 600; opacity: 0.8; }
        .relay-card .status { font-size: 11px; margin-top: 5px; display: block; letter-spacing: 1px; }
        .relay-card.ON { 
            background: rgba(157, 80, 187, 0.2); border-color: var(--purple-main);
            box-shadow: 0 0 15px rgba(157, 80, 187, 0.3);
        }
        .relay-card.ON i { color: var(--purple-main); text-shadow: 0 0 10px var(--purple-main); }
        .relay-card.OFF { opacity: 0.6; }

        .chat-card {
            background: var(--card-bg); border-radius: 25px; border: 1px solid rgba(255,255,255,0.1);
            display: flex; flex-direction: column; height: 450px; overflow: hidden;
        }
        .chat-window {
            flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px;
        }
        .msg { max-width: 80%; padding: 12px 16px; border-radius: 18px; font-size: 14px; line-height: 1.5; }
        .user-msg { align-self: flex-end; background: var(--purple-main); color: white; border-bottom-right-radius: 4px; }
        .ai-msg { align-self: flex-start; background: rgba(255,255,255,0.1); color: #eee; border-bottom-left-radius: 4px; }
        .system-msg { align-self: center; background: rgba(255, 159, 67, 0.1); color: #ff9f43; border: 1px dashed #ff9f43; font-size: 12px; border-radius: 10px; }

        .input-area { padding: 15px; background: rgba(0,0,0,0.2); display: flex; gap: 10px; }
        .input-area input {
            flex: 1; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
            border-radius: 50px; padding: 12px 20px; color: white; outline: none; font-size: 15px;
        }
        .input-area input:focus { border-color: var(--purple-main); }
        .input-area button {
            background: var(--purple-main); color: white; border: none;
            width: 45px; height: 45px; border-radius: 50%; cursor: pointer;
            display: flex; align-items: center; justify-content: center; transition: 0.3s;
        }
        .input-area button:hover { transform: scale(1.1); }

        @media (max-width: 600px) {
            header { flex-direction: column; gap: 8px; }
            .grid { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <header>
        <h1>RoomX</h1>
        <div id="conn-status" class="conn-badge">
            <i class="fas fa-circle"></i> <span id="conn-text">HomeX Disconnected</span>
        </div>
    </header>

    <div class="container">
        <div id="device-grid" class="grid">
            <div class="relay-card OFF"><span>Loading Sync...</span></div>
        </div>

        <div class="chat-card">
            <div class="chat-window" id="chat-window">
                <div class="msg ai-msg">Welcome back Zion! RoomX Unified Hub is online. Send a text or use your ESP32 Voice mic.</div>
            </div>
            <div class="input-area">
                <input type="text" id="chat-msg" placeholder="Type a message or command..." onkeypress="handleKeyPress(event)">
                <button id="send-btn" onclick="sendManualCommand()"><i class="fas fa-paper-plane"></i></button>
            </div>
        </div>
    </div>

    <script>
        const chatWindow = document.getElementById('chat-window');
        let isSending = false;

        function updateHub() {
            fetch('{{ fb_url }}')
                .then(res => res.json())
                .then(data => {
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
                        grid.innerHTML += `
                            <div class="relay-card ${state}">
                                <i class="fas ${dev.icon} ${state === 'ON' && dev.id === 'relay_3' ? 'fa-spin' : ''}"></i>
                                <span>${dev.name}</span>
                                <span class="status">${state}</span>
                            </div>`;
                    });
                });

            fetch('/get-latest-events')
                .then(res => res.json())
                .then(data => {
                    const badge = document.getElementById('conn-status');
                    const text = document.getElementById('conn-text');
                    if(data.esp32_online) {
                        badge.classList.add('online');
                        text.innerText = "HomeX Connected to Internet";
                    } else {
                        badge.classList.remove('online');
                        text.innerText = "HomeX Disconnected";
                    }

                    if (data.new_messages && data.new_messages.length > 0) {
                        data.new_messages.forEach(msg => {
                            if(msg.type === 'voice_start') {
                                chatWindow.innerHTML += `<div class="msg system-msg"><i class="fas fa-microphone"></i> ESP32 Audio Streaming...</div>`;
                            } else {
                                chatWindow.innerHTML += `<div class="msg user-msg" style="border: 1px dashed rgba(255,255,255,0.4);"><i class="fas fa-microphone" style="font-size:10px; margin-right:5px;"></i>${msg.user}</div>`;
                                chatWindow.innerHTML += `<div class="msg ai-msg">${msg.ai}</div>`;
                            }
                        });
                        chatWindow.scrollTop = chatWindow.scrollHeight;
                    }
                });
        }

        function sendManualCommand() {
            const input = document.getElementById('chat-msg');
            const btn = document.getElementById('send-btn');
            const cmd = input.value.trim();
            if(!cmd || isSending) return;

            isSending = true; input.disabled = true; btn.disabled = true;
            chatWindow.innerHTML += `<div class="msg user-msg">${cmd}</div>`;
            chatWindow.scrollTop = chatWindow.scrollHeight;

            fetch('/voice-command', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ text: cmd })
            })
            .then(res => res.json())
            .then(data => {
                chatWindow.innerHTML += `<div class="msg ai-msg">${data.reply}</div>`;
                chatWindow.scrollTop = chatWindow.scrollHeight;
                input.value = ''; input.disabled = false; btn.disabled = false; isSending = false;
                updateHub();
            })
            .catch(() => {
                input.disabled = false; btn.disabled = false; isSending = false;
            });
        }

        function handleKeyPress(e) { if(e.key === 'Enter') sendManualCommand(); }
        setInterval(updateHub, 1500);
        updateHub();
    </script>
</body>
</html>
"""

ui_pending_messages = []

@app.route('/', methods=['GET'])
def home():
    return render_template_string(DASHBOARD_TEMPLATE, fb_url=FIREBASE_URL), 200

@app.route('/get-latest-events', methods=['GET'])
def get_latest_events():
    global ui_pending_messages, last_esp32_seen
    is_online = (time.time() - last_esp32_seen) < 5.0
    messages_to_send = list(ui_pending_messages)
    ui_pending_messages.clear()
    
    return jsonify({
        "esp32_online": is_online,
        "new_messages": messages_to_send
    })

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global audio_buffer, silent_chunks_count, has_speech_started, last_esp32_seen, ui_pending_messages
    
    data = request.get_json() or {}
    audio_base64 = data.get("audio")
    command_text = data.get("text", "").strip()
    
    if command_text and not audio_base64:
        return process_with_groq(command_text, source="manual")
        
    if audio_base64:
        last_esp32_seen = time.time()  # Fix applied here (standard assignment)
        
        chunk_bytes = base64.b64decode(audio_base64)
        audio_data = np.frombuffer(chunk_bytes, dtype=np.int16)
        
        if len(audio_data) > 0:
            amplitude = np.max(np.abs(audio_data))
            
            if amplitude > SILENCE_THRESHOLD:
                audio_buffer.extend(chunk_bytes)
                silent_chunks_count = 0
                if not has_speech_started:
                    has_speech_started = True
                    ui_pending_messages.append({"type": "voice_start"}) 
            else:
                if has_speech_started:
                    audio_buffer.extend(chunk_bytes)
                    silent_chunks_count += 1
        
        if has_speech_started and silent_chunks_count >= SILENCE_DURATION_CHUNKS:
            full_audio = bytes(audio_buffer)
            audio_buffer = bytearray()
            silent_chunks_count = 0
            has_speech_started = False
            
            if len(full_audio) >= 20000:
                return transcribe_and_process(full_audio)
                
        return jsonify({"status": "Streaming", "esp32_online": True}), 200

    return jsonify({"error": "No input"}), 400

def transcribe_and_process(audio_bytes):
    try:
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

        transcription = groq_client.audio.transcriptions.create(
            file=wav_io,
            model="whisper-large-v3",
            language="en"
        )
        return process_with_groq(transcription.text, source="voice")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def process_with_groq(user_message, source="manual"):
    global chat_history, ui_pending_messages
    
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
        
        if source == "voice":
            ui_pending_messages.append({"user": user_message, "ai": ai_reply})
            
        return jsonify({"status": "Success", "reply": ai_reply}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
