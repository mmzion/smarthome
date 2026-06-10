import os
import json
import base64
import time
import numpy as np
from flask import Flask, request, jsonify, render_template_string
from google import genai
from google.genai import types
import requests

app = Flask(__name__)

# কনফিগারেশন
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

# সার্ভার মেমরি স্টেট
audio_buffer = bytearray()
SILENCE_THRESHOLD = 500  
SILENCE_DURATION_CHUNKS = 15  
silent_chunks_count = 0
has_speech_started = False
last_received_status = "Waiting for input..."
last_ai_reply = "Hello Zion! I am ready to chat and manage your smart home." # ডিফল্ট রিপ্লাই

# ড্যাশবোর্ড UI (চ্যাট রিপ্লাই বক্স সহ উন্নত করা হয়েছে)
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zion's Smart Home Control Panel</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #00adb5; border-bottom: 2px solid #393e46; padding-bottom: 10px; }
        .card { background: #1e1e1e; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; }
        .relay-card { background: #2a2a2a; padding: 15px; border-radius: 8px; text-align: center; font-weight: bold; border: 1px solid #333; }
        .ON { border-color: #00adb5; color: #00adb5; background: rgba(0, 173, 181, 0.1); }
        .OFF { border-color: #ff2e63; color: #ff2e63; background: rgba(255, 46, 99, 0.1); }
        .status-badge { display: inline-block; padding: 5px 10px; border-radius: 5px; font-size: 14px; background: #393e46; color: #eee; }
        .listening { background: #00adb5; color: #fff; animation: pulse 1.5s infinite; }
        
        /* চ্যাট বাবল স্টাইল */
        .chat-box { background: #2a2a2a; padding: 15px; border-radius: 8px; border-left: 4px solid #00adb5; margin-bottom: 15px; min-height: 40px; font-size: 16px; line-height: 1.5; }
        .chat-input-group { display: flex; gap: 10px; margin-top: 15px; }
        .chat-input { flex: 1; padding: 12px; border-radius: 5px; border: 1px solid #393e46; background: #2a2a2a; color: #fff; font-size: 16px; }
        .chat-input:focus { border-color: #00adb5; outline: none; }
        .chat-btn { padding: 12px 24px; border-radius: 5px; border: none; background: #00adb5; color: #fff; font-size: 16px; cursor: pointer; font-weight: bold; }
        .chat-btn:hover { background: #008c9e; }
        .chat-btn:disabled { background: #555; cursor: not-allowed; }
        
        @keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎙️ Gemini AI Smart Home Hub</h1>
        
        <div class="card">
            <h3>Server & Voice Engine Status</h3>
            <p><strong>API Connection:</strong> <span class="status-badge" style="background:#4caf50;">Connected (Gemini 3.5 Flash)</span></p>
            <p><strong>Voice Assistant State:</strong> <span id="v-state" class="status-badge">Idle</span></p>
            <p><strong>Last Event:</strong> <span id="l-event">{{ last_status }}</span></p>
        </div>

        <div class="card">
            <h3>💬 Chat with Gemini</h3>
            <div class="chat-box" id="ai-response-box">{{ ai_reply }}</div>
            <div class="chat-input-group">
                <input type="text" id="chat-msg" class="chat-input" placeholder="Say hi or give a command..." onkeypress="handleKeyPress(event)">
                <button id="send-btn" class="chat-btn" onclick="sendManualCommand()">Send</button>
            </div>
        </div>

        <div class="card">
            <h3>Live Device Matrix (Relays)</h3>
            <div id="device-grid" class="grid">
                <div class="relay-card">Loading...</div>
            </div>
        </div>
    </div>

    <script>
        function updateDashboard() {
            fetch('{{ fb_url }}')
                .then(response => response.json())
                .then(data => {
                    const grid = document.getElementById('device-grid');
                    grid.innerHTML = '';
                    const names = { relay_1: "Main Light", relay_2: "Dim Light", relay_3: "Fan", relay_4: "Socket" };
                    
                    for (let key in data) {
                        if (names[key]) {
                            const state = data[key];
                            grid.innerHTML += `<div class="relay-card ${state}">${names[key]}<br><span style="font-size:12px">${state}</span></div>`;
                        }
                    }
                });

            fetch('/server-stats')
                .then(response => response.json())
                .then(stats => {
                    const vState = document.getElementById('v-state');
                    vState.innerText = stats.listening ? "Listening..." : "Idle";
                    if(stats.listening) vState.classList.add('listening');
                    else vState.classList.remove('listening');
                    document.getElementById('l-event').innerText = stats.last_status;
                    document.getElementById('ai-response-box').innerText = stats.ai_reply;
                });
        }

        function sendManualCommand() {
            const inputField = document.getElementById('chat-msg');
            const btn = document.getElementById('send-btn');
            const command = inputField.value.trim();
            
            if (!command) return;

            inputField.disabled = true;
            btn.disabled = true;
            btn.innerText = "Sending...";

            fetch('/voice-command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: command })
            })
            .then(response => response.json())
            .then(data => {
                inputField.value = '';
                inputField.disabled = false;
                btn.disabled = false;
                btn.innerText = "Send";
                updateDashboard();
            })
            .catch(err => {
                console.error(err);
                inputField.disabled = false;
                btn.disabled = false;
                btn.innerText = "Send";
            });
        }

        function handleKeyPress(event) {
            if (event.key === 'Enter') {
                sendManualCommand();
            }
        }
        
        setInterval(updateDashboard, 2000);
        updateDashboard();
    </script>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def health_check():
    global last_received_status, last_ai_reply
    return render_template_string(DASHBOARD_TEMPLATE, fb_url=FIREBASE_URL, last_status=last_received_status, ai_reply=last_ai_reply), 200

@app.route('/server-stats', methods=['GET'])
def server_stats():
    global has_speech_started, last_received_status, last_ai_reply
    return jsonify({"listening": has_speech_started, "last_status": last_received_status, "ai_reply": last_ai_reply})

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global audio_buffer, silent_chunks_count, has_speech_started, last_received_status
    
    data = request.get_json()
    audio_base64 = data.get("audio", None)
    command_text = data.get("text", "")
    
    if command_text and not audio_base64:
        last_received_status = f"Manual command received."
        return process_with_gemini(command_text, is_audio=False)
        
    if audio_base64:
        chunk_bytes = base64.b64decode(audio_base64)
        audio_data = np.frombuffer(chunk_bytes, dtype=np.int16)
        
        if len(audio_data) > 0:
            amplitude = np.max(np.abs(audio_data))
            
            if amplitude > SILENCE_THRESHOLD:
                audio_buffer.extend(chunk_bytes)
                silent_chunks_count = 0
                has_speech_started = True
                last_received_status = "Capturing active speech..."
            else:
                if has_speech_started:
                    audio_buffer.extend(chunk_bytes)
                    silent_chunks_count += 1
        
        if has_speech_started and silent_chunks_count >= SILENCE_DURATION_CHUNKS:
            full_audio = bytes(audio_buffer)
            audio_buffer = bytearray()
            silent_chunks_count = 0
            has_speech_started = False
            
            last_received_status = "Analyzing audio via Gemini..."
            return process_with_gemini(full_audio, is_audio=True)
            
        return jsonify({"status": "Streaming", "listening": has_speech_started}), 200

    return jsonify({"error": "No valid input found"}), 400

def process_with_gemini(contents_data, is_audio=False):
    global last_received_status, last_ai_reply
    contents = []
    
    if is_audio:
        contents.append({"inline_data": {"mime_type": "audio/wav", "data": contents_data}})
    else:
        contents.append(contents_data)

    # নতুন সিস্টেম ইন্সট্রাকশন: এটি জেমিনিকে টেক্সট রিপ্লাই এবং রিলে কন্ট্রোল দুটোই একসাথে করতে বাধ্য করবে
    system_instruction = """You are an AI Smart Home Assistant. 
    You must always reply in a friendly manner. You can chat casually, answer questions, or process smart home commands.
    You must respond ONLY in the following JSON format:
    {
      "reply": "Your conversational text response here to the user",
      "relays": {"relay_1": "ON/OFF", "relay_2": "ON/OFF", "relay_3": "ON/OFF", "relay_4": "ON/OFF"}
    }
    Important: If the user is just chatting (e.g., 'hi', 'how are you') and NOT giving a home control command, do not change the relay states. Instead, fetch current relay states from the environment or default to keeping them as they are. Keep the exact format."""
    
    # ফায়ারবেস থেকে কারেন্ট রিলে স্টেট নিয়ে আসা (যাতে চ্যাট করার সময় লাইট অফ না হয়ে যায়)
    current_relays = {"relay_1": "OFF", "relay_2": "OFF", "relay_3": "OFF", "relay_4": "OFF"}
    try:
        fb_res = requests.get(FIREBASE_URL)
        if fb_res.status_code == 200 and fb_res.json():
            current_relays = fb_res.json()
    except:
        pass

    # জেমিনিকে কারেন্ট স্টেট জানিয়ে দেওয়া যাতে সে চ্যাটের সময় এগুলো পরিবর্তন না করে
    full_instruction = f"{system_instruction}\nCurrent Relays State: {json.dumps(current_relays)}"

    max_retries = 3      
    retry_delay = 2      
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=full_instruction, response_mime_type="application/json")
            )
            
            result = json.loads(response.text)
            
            # ১. টেক্সট রিপ্লাই আলাদা করা
            last_ai_reply = result.get("reply", "Command processed.")
            
            # ২. রিলে স্টেট আপডেট করা
            updates = result.get("relays", current_relays)
            requests.patch(FIREBASE_URL, json=updates)
            
            last_received_status = "Success! Dashboard and Firebase updated."
            return jsonify({"status": "Success", "reply": last_ai_reply, "updates": updates}), 200
                
        except Exception as e:
            if "503" in str(e) or "429" in str(e):
                if attempt < max_retries - 1:
                    last_received_status = f"Gemini busy (503). Retrying in {retry_delay}s... (Attempt {attempt + 1}/{max_retries})"
                    time.sleep(retry_delay)
                    retry_delay *= 2  
                    continue
            
            last_received_status = f"Error after {attempt + 1} attempts: {str(e)}"
            return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
