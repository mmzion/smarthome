import os
import json
import base64
import numpy as np
from flask import Flask, request, jsonify, render_template_string
from google import genai
from google.genai import types
import requests

app = Flask(__name__)

# কনফিগারেশন
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

# গ্লোবাল মেমরি স্টেট (স্মার্ট সেভার মোড)
audio_buffer = bytearray()
SILENCE_THRESHOLD = 650  # থ্রেশহোল্ড সামান্য বাড়ানো হলো নয়েজ ফিল্টার করতে
SILENCE_DURATION_CHUNKS = 12  
silent_chunks_count = 0
has_speech_started = False

# কোটা সেভার ট্র্যাকিং
daily_api_calls = 0
last_command_text = ""
last_ai_reply = "Hello! Quota Saver Mode Activated. 20 daily calls remaining."

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Home Hub (Quota Saver)</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background-color: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #00adb5; border-bottom: 2px solid #393e46; padding-bottom: 10px; margin-bottom: 20px; }
        .card { background: #1e1e1e; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; }
        .relay-card { background: #2a2a2a; padding: 15px; border-radius: 8px; text-align: center; font-weight: bold; border: 1px solid #333; }
        .ON { border-color: #00adb5; color: #00adb5; background: rgba(0, 173, 181, 0.1); }
        .OFF { border-color: #ff2e63; color: #ff2e63; background: rgba(255, 46, 99, 0.1); }
        .chat-box { background: #2a2a2a; padding: 15px; border-radius: 8px; border-left: 4px solid #00adb5; margin-bottom: 15px; min-height: 30px; font-size: 16px; }
        .chat-input-group { display: flex; gap: 10px; }
        .chat-input { flex: 1; padding: 12px; border-radius: 5px; border: 1px solid #393e46; background: #2a2a2a; color: #fff; font-size: 16px; }
        .chat-btn { padding: 12px 24px; border-radius: 5px; border: none; background: #00adb5; color: #fff; font-size: 16px; cursor: pointer; font-weight: bold; }
        .chat-btn:disabled { background: #555; }
        .quota-text { font-size: 12px; color: #ff9f43; margin-top: 5px; text-align: right; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎙️ Smart Home AI Hub</h1>
        
        <div class="card">
            <div class="chat-box" id="ai-response-box">{{ ai_reply }}</div>
            <div class="chat-input-group">
                <input type="text" id="chat-msg" class="chat-input" placeholder="Type command here..." onkeypress="handleKeyPress(event)">
                <button id="send-btn" class="chat-btn" onclick="sendManualCommand()">Send</button>
            </div>
            <div class="quota-text" id="quota-display">API Status: Checked</div>
        </div>

        <div class="card">
            <h3>Live Relays</h3>
            <div id="device-grid" class="grid">
                <div class="relay-card">Loading...</div>
            </div>
        </div>
    </div>

    <script>
        let isSending = false;
        function updateDashboard() {
            fetch('{{ fb_url }}')
                .then(res => res.json())
                .then(data => {
                    const grid = document.getElementById('device-grid');
                    grid.innerHTML = '';
                    const names = { relay_1: "Main Light", relay_2: "Dim Light", relay_3: "Fan", relay_4: "Socket" };
                    for (let key in data) {
                        if (names[key]) {
                            grid.innerHTML += `<div class="relay-card ${data[key]}">${names[key]}<br><span style="font-size:12px">${data[key]}</span></div>`;
                        }
                    }
                });

            if(!isSending) {
                fetch('/server-stats')
                    .then(res => res.json())
                    .then(stats => {
                        document.getElementById('ai-response-box').innerText = stats.ai_reply;
                        document.getElementById('quota-display').innerText = "Today's Server API Calls: " + stats.calls_count + "/20";
                    });
            }
        }

        function sendManualCommand() {
            const inputField = document.getElementById('chat-msg');
            const btn = document.getElementById('send-btn');
            const command = inputField.value.trim();
            if (!command) return;

            isSending = true;
            inputField.disabled = true;
            btn.disabled = true;
            btn.innerText = "Wait...";

            fetch('/voice-command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: command })
            })
            .then(res => res.json())
            .then(data => {
                document.getElementById('ai-response-box').innerText = data.reply || data.error;
                inputField.value = '';
                inputField.disabled = false;
                btn.disabled = false;
                btn.innerText = "Send";
                isSending = false;
                updateDashboard();
            })
            .catch(() => {
                inputField.disabled = false;
                btn.disabled = false;
                btn.innerText = "Send";
                isSending = false;
            });
        }

        function handleKeyPress(e) { if (e.key === 'Enter') sendManualCommand(); }
        setInterval(updateDashboard, 2000);
        updateDashboard();
    </script>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def health_check():
    global last_ai_reply
    return render_template_string(DASHBOARD_TEMPLATE, fb_url=FIREBASE_URL, ai_reply=last_ai_reply), 200

@app.route('/server-stats', methods=['GET'])
def server_stats():
    global last_ai_reply, daily_api_calls
    return jsonify({"ai_reply": last_ai_reply, "calls_count": daily_api_calls})

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global audio_buffer, silent_chunks_count, has_speech_started, last_command_text, daily_api_calls, last_ai_reply
    data = request.get_json() or {}
    audio_base64 = data.get("audio")
    command_text = data.get("text", "").strip()
    
    # ১. টেক্সট ডুপ্লিকেট ফিল্টার (একই জিনিস বারবার পাঠালে এপিআই কল ব্লক করবে)
    if command_text and not audio_base64:
        if command_text.lower() == last_command_text.lower():
            return jsonify({"status": "Ignored", "reply": f"You just said that! (API Saved) -> {last_ai_reply}"}), 200
        last_command_text = command_text
        return process_with_gemini(command_text, is_audio=False)
        
    # ২. অডিও ইনপুট প্রসেস
    if audio_base64:
        chunk_bytes = base64.b64decode(audio_base64)
        audio_data = np.frombuffer(chunk_bytes, dtype=np.int16)
        
        if len(audio_data) > 0:
            if np.max(np.abs(audio_data)) > SILENCE_THRESHOLD:
                audio_buffer.extend(chunk_bytes)
                silent_chunks_count = 0
                has_speech_started = True
            else:
                if has_speech_started:
                    audio_buffer.extend(chunk_bytes)
                    silent_chunks_count += 1
        
        if has_speech_started and silent_chunks_count >= SILENCE_DURATION_CHUNKS:
            full_audio = bytes(audio_buffer)
            
            # স্মার্ট ফিল্টার: অডিও ডাটা যদি ১.৫ সেকেন্ডের চেয়ে ছোট হয় (যেমন < ৪৮০০০ বাইটস), তবে ফালতু নয়েজ মনে করে ড্রপ করবে
            if len(full_audio) < 45000:
                audio_buffer = bytearray()
                silent_chunks_count = 0
                has_speech_started = False
                return jsonify({"status": "Dropped", "message": "Audio too short, probably background noise."}), 200

            audio_buffer = bytearray()
            silent_chunks_count = 0
            has_speech_started = False
            return process_with_gemini(full_audio, is_audio=True)
            
        return jsonify({"status": "Streaming"}), 200

    return jsonify({"error": "No input"}), 400

def process_with_gemini(contents_data, is_audio=False):
    global last_ai_reply, daily_api_calls
    
    # গুগল ফ্রি টায়ার সেফগার্ড (সার্ভার ২০টার বেশি কল পাঠাবেই না)
    if daily_api_calls >= 20:
        last_ai_reply = "⚠️ Daily Google Free Quota (20/20) exhausted! Please try again tomorrow or upgrade API plan."
        return jsonify({"error": "Quota limit reached", "reply": last_ai_reply}), 429

    contents = [{"inline_data": {"mime_type": "audio/wav", "data": contents_data}}] if is_audio else [contents_data]
    system_instruction = """You are a fast Smart Home AI. Reply friendly and output current relay states.
    Return ONLY JSON: {"reply": "text response", "relays": {"relay_1": "ON/OFF", "relay_2": "ON/OFF", "relay_3": "ON/OFF", "relay_4": "ON/OFF"}}"""
    
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=system_instruction, response_mime_type="application/json")
            )
            
            # সফল কলের জন্য কাউন্টার বাড়ানো
            daily_api_calls += 1
            
            result = json.loads(response.text)
            last_ai_reply = result.get("reply", "")
            updates = result.get("relays", {})
            
            if updates:
                requests.patch(FIREBASE_URL, json=updates, timeout=1.5)
                
            return jsonify({"status": "Success", "reply": last_ai_reply}), 200
        except Exception as e:
            if "429" in str(e):
                last_ai_reply = "API Limit hit. Cooling down..."
                return jsonify({"error": "Rate limit", "reply": last_ai_reply}), 429
            if attempt == 0: continue
            
    last_ai_reply = "System error, please try again."
    return jsonify({"error": "Failed"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
