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

# সার্ভার মেমরি স্টেট (গ্লোবাল ভেরিয়েবল)
audio_buffer = bytearray()
SILENCE_THRESHOLD = 500  # মাইক্রোফোনের নয়েজ লেভেল অনুযায়ী এটি পরিবর্তন করতে পারেন
SILENCE_DURATION_CHUNKS = 15  # পরপর কতগুলো চঙ্ক নীরব থাকলে ধরে নেওয়া হবে কথা শেষ (প্রায় ১.৫ - ২ সেকেন্ড)
silent_chunks_count = 0
has_speech_started = False
last_received_status = "Waiting for input..."

# ড্যাশবোর্ড UI (HTML/CSS/JS)
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
            <h3>💬 Manual Chat with Gemini</h3>
            <p style="font-size: 14px; color: #aaa;">Type a command to control your home (e.g., "turn on main light and fan")</p>
            <div class="chat-input-group">
                <input type="text" id="chat-msg" class="chat-input" placeholder="Type your command here..." onkeypress="handleKeyPress(event)">
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
            // ফায়ারবেস থেকে লাইভ রিলে ডাটা ফেচ করা
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

            // লাইভ ভয়েস স্ট্যাটাস এবং লাস্ট ইভেন্ট আপডেট
            fetch('/server-stats')
                .then(response => response.json())
                .then(stats => {
                    const vState = document.getElementById('v-state');
                    vState.innerText = stats.listening ? "Listening..." : "Idle";
                    if(stats.listening) vState.classList.add('listening');
                    else vState.classList.remove('listening');
                    document.getElementById('l-event').innerText = stats.last_status;
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
    """হোম পেজে পুরো সার্ভার ও ডিভাইসের ডিটেইলস প্যানেল দেখাবে (cron-job.org এর 404 ফিক্স)"""
    return render_template_string(DASHBOARD_TEMPLATE, fb_url=FIREBASE_URL, last_status=last_received_status), 200

@app.route('/server-stats', methods=['GET'])
def server_stats():
    """ফ্রন্টএন্ডের ব্যাকগ্রাউন্ড রিফ্রেসের জন্য মেমরি স্ট্যাটাস এপিআই"""
    global has_speech_started, last_received_status
    return jsonify({"listening": has_speech_started, "last_status": last_received_status})

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global audio_buffer, silent_chunks_count, has_speech_started, last_received_status
    
    data = request.get_json()
    audio_base64 = data.get("audio", None)
    command_text = data.get("text", "")
    
    # ১. ম্যানুয়াল টেক্সট কমান্ড হ্যান্ডেল করা
    if command_text and not audio_base64:
        last_received_status = f"Manual command: '{command_text}'"
        return process_with_gemini(command_text, is_audio=False)
        
    # ২. ESP32 থেকে আসা অডিও স্ট্রিম হ্যান্ডেল করা (অনবরত লুপের জন্য)
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
        
        # কথা শেষ হওয়ার সিদ্ধান্ত সার্ভার নিজে নেবে
        if has_speech_started and silent_chunks_count >= SILENCE_DURATION_CHUNKS:
            full_audio = bytes(audio_buffer)
            
            # স্টেট রিসেট (পরবর্তী ভয়েস কমান্ডের জন্য)
            audio_buffer = bytearray()
            silent_chunks_count = 0
            has_speech_started = False
            
            last_received_status = "Analyzing audio via Gemini..."
            return process_with_gemini(full_audio, is_audio=True)
            
        return jsonify({"status": "Streaming", "listening": has_speech_started}), 200

    return jsonify({"error": "No valid input found"}), 400

def process_with_gemini(contents_data, is_audio=False):
    """জেমিনি এপিআই কল করার সেন্ট্রাল ফাংশন (Exponential Backoff অটো-রিট্রাই সহ)"""
    global last_received_status
    contents = []
    
    if is_audio:
        contents.append({"inline_data": {"mime_type": "audio/wav", "data": contents_data}})
    else:
        contents.append(contents_data)

    system_instruction = """You are an AI Smart Home Assistant. 
    Analyze the input and return ONLY a JSON object for relays: 
    {"relay_1": "ON/OFF", "relay_2": "ON/OFF", "relay_3": "ON/OFF", "relay_4": "ON/OFF"}"""
    
    max_retries = 3      # সর্বোচ্চ ৩ বার চেষ্টা করবে
    retry_delay = 2      # প্রথমবার বিরতি ২ সেকেন্ড
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-3.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=system_instruction, response_mime_type="application/json")
            )
            
            updates = json.loads(response.text)
            requests.patch(FIREBASE_URL, json=updates)
            last_received_status = f"Success! Output: {response.text}"
            return jsonify({"status": "Success", "updates": updates}), 200
                
        except Exception as e:
            # যদি এররটি গুগলের ওভার-ট্রাফিক (503) বা রেট লিমিটের (429) কারণে হয়
            if "503" in str(e) or "429" in str(e):
                if attempt < max_retries - 1:
                    last_received_status = f"Gemini busy (503). Retrying in {retry_delay}s... (Attempt {attempt + 1}/{max_retries})"
                    print(last_received_status)
                    time.sleep(retry_delay)
                    retry_delay *= 2  # প্রতিবার ওয়েটিং টাইম দ্বিগুণ হবে (২ সেকেন্ড, ৪ সেকেন্ড...)
                    continue
            
            # ৩ বার ট্রাই করার পরও ফেইল হলে বা অন্য কোনো সাধারণ কোড এরর হলে ফাইনাল এরর দেবে
            last_received_status = f"Error after {attempt + 1} attempts: {str(e)}"
            return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
