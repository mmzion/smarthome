import os
import json
import base64
import numpy as np
from flask import Flask, request, jsonify, render_template_string
from groq import Groq
import requests

app = Flask(__name__)

# জেমিনি বাদ দিয়ে এখন Groq ক্লায়েন্ট কনফিগারেশন
# Render-এর Environment-এ GROQ_API_KEY নামে আপনার কী-টি সেভ করবেন
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

# গ্লোবাল মেমরি স্টেট (সবচেয়ে হালকা এবং ফাস্ট)
audio_buffer = bytearray()
SILENCE_THRESHOLD = 600  
SILENCE_DURATION_CHUNKS = 10  
silent_chunks_count = 0
has_speech_started = False
last_ai_reply = "Hello Zion! Groq Engine is active. Unlimited mode on."

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zion's Smart Home (Groq Powered)</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; background-color: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #ff9f43; border-bottom: 2px solid #393e46; padding-bottom: 10px; margin-bottom: 20px; }
        .card { background: #1e1e1e; padding: 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; }
        .relay-card { background: #2a2a2a; padding: 15px; border-radius: 8px; text-align: center; font-weight: bold; border: 1px solid #333; }
        .ON { border-color: #ff9f43; color: #ff9f43; background: rgba(255, 159, 67, 0.1); }
        .OFF { border-color: #ff2e63; color: #ff2e63; background: rgba(255, 46, 99, 0.1); }
        .chat-box { background: #2a2a2a; padding: 15px; border-radius: 8px; border-left: 4px solid #ff9f43; margin-bottom: 15px; min-height: 30px; font-size: 16px; }
        .chat-input-group { display: flex; gap: 10px; }
        .chat-input { flex: 1; padding: 12px; border-radius: 5px; border: 1px solid #393e46; background: #2a2a2a; color: #fff; font-size: 16px; }
        .chat-btn { padding: 12px 24px; border-radius: 5px; border: none; background: #ff9f43; color: #fff; font-size: 16px; cursor: pointer; font-weight: bold; }
        .chat-btn:disabled { background: #555; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚡ Ultra Fast Groq AI Hub</h1>
        
        <div class="card">
            <div class="chat-box" id="ai-response-box">{{ ai_reply }}</div>
            <div class="chat-input-group">
                <input type="text" id="chat-msg" class="chat-input" placeholder="Ask anything or control home..." onkeypress="handleKeyPress(event)">
                <button id="send-btn" class="chat-btn" onclick="sendManualCommand()">Send</button>
            </div>
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
                document.getElementById('ai-response-box').innerText = data.reply;
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
        setInterval(updateDashboard, 1500);
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
    global last_ai_reply
    return jsonify({"ai_reply": last_ai_reply})

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global audio_buffer, silent_chunks_count, has_speech_started
    data = request.get_json() or {}
    audio_base64 = data.get("audio")
    command_text = data.get("text", "").strip()
    
    # চ্যাট ইনপুট হ্যান্ডেল করা
    if command_text and not audio_base64:
        return process_with_groq(command_text)
        
    # ESP32 থেকে আসা অডিও ইনপুট প্রসেস করা
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
            # দ্রষ্টব্য: Groq সরাসরি অডিও ফাইল ইনপুট নেয় না টেক্সট জেনারেশন মডেলে।
            # তাই ভয়েস টু টেক্সট (Whisper) অথবা অডিওর জন্য আমরা পরবর্তীতে আরেকটি এপিআই রুট করব।
            # আপাতত টেক্সট চ্যাট ইন্টারফেস সুপার-ফাস্ট মোডে রান করার জন্য সেট করা হলো।
            audio_buffer = bytearray()
            silent_chunks_count = 0
            has_speech_started = False
            return jsonify({"status": "Voice features optimization needed for Groq"}), 200
            
        return jsonify({"status": "Streaming"}), 200

    return jsonify({"error": "No input"}), 400

def process_with_groq(user_message):
    global last_ai_reply
    
    system_instruction = """You are a super fast AI Smart Home Assistant. Reply to user queries warmly.
    You must output valid JSON data ONLY. Use this strict scheme:
    {"reply": "your textual conversation here", "relays": {"relay_1": "ON/OFF", "relay_2": "ON/OFF", "relay_3": "ON/OFF", "relay_4": "ON/OFF"}}
    Do not change relay states unless specifically commanded by the user."""

    try:
        # Groq-এর সবচেয়ে শক্তিশালী Llama 3.3 মডেল ব্যবহার করা হয়েছে
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_message}
            ],
            response_format={"type": "json_object"} # এটি কোডকে ফাস্ট এবং অবজেক্ট রিটার্ন নিশ্চিত করে
        )
        
        response_text = completion.choices[0].message.content
        result = json.loads(response_text)
        
        last_ai_reply = result.get("reply", "")
        updates = result.get("relays", {})
        
        if updates:
            requests.patch(FIREBASE_URL, json=updates, timeout=1.5)
            
        return jsonify({"status": "Success", "reply": last_ai_reply}), 200
    except Exception as e:
        last_ai_reply = f"Groq Error: {str(e)}"
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
