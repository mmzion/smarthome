import os
import json
import time
import io
import requests
from flask import Flask, request, jsonify, render_template_string, send_file
from groq import Groq
from gtts import gTTS

app = Flask(__name__)

# Groq Configuration
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

# Global System States
last_recorded_wav = None
chat_history = []
MAX_HISTORY_LENGTH = 7 # অ্যাসিস্ট্যান্টের মেমোরি কনটেক্সট বাড়ানোর জন্য হিস্ট্রি লেন্থ বাড়ানো হলো
last_esp32_seen = 0  
esp32_current_state = "Disconnected" 
ui_pending_messages = []
current_tts_audio = None

# --- ইন্টারনেট সার্চ ইঞ্জিন (ফ্রি ও রিয়েল-টাইম) ---
def internet_search(query):
    try:
        # DDG API ব্যবহার করে যেকোনো লাইভ ইনফরমেশন স্ক্র্যাপ করার অত্যন্ত ফাস্ট মেকানিজম
        url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1"
        res = requests.get(url, timeout=2.5)
        if res.status_code == 200:
            data = res.json()
            # যদি সরাসরি ডিরেক্ট টেক্সট আনসার পাওয়া যায়
            if data.get("AbstractText"):
                return data["AbstractText"]
            # বিকল্প ব্যাকআপ সোর্স (রিলিজড টপিকস)
            elif data.get("RelatedTopics") and len(data["RelatedTopics"]) > 0:
                return data["RelatedTopics"][0].get("Text", "No deep info found.")
        return "I search the web but couldn't get definitive real-time facts."
    except Exception as e:
        return f"Internet search temporarily unavailable: {str(e)}"

# --- (ড্যাশবোর্ড টেমপ্লেট আগের মতোই হুবহু অপরিবর্তিত থাকবে) ---
DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RoomX | Unified Intelligence Hub</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root { --bg: #0f0c29; --purple-main: #9d50bb; --card-bg: rgba(255, 255, 255, 0.05); --text: #f5f5f5; --green-glow: #00ff87; --amber-glow: #ff9f43; --red-glow: #ff2e63; }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { font-family: 'Segoe UI', sans-serif; background: var(--bg); background-image: radial-gradient(circle at 50% 50%, #1a1a3a 0%, #0f0c29 100%); color: var(--text); margin: 0; padding: 0; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }
        header { width: 100%; padding: 20px; text-align: center; background: rgba(0,0,0,0.3); backdrop-filter: blur(10px); border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; display: flex; justify-content: center; align-items: center; gap: 15px; }
        header h1 { margin: 0; font-size: 28px; letter-spacing: 2px; font-weight: 800; color: #fff; }
        .conn-badge { background: rgba(0,0,0,0.4); border: 1px solid var(--red-glow); color: var(--red-glow); padding: 6px 14px; border-radius: 50px; font-size: 12px; font-weight: 600; display: flex; align-items: center; gap: 8px; transition: 0.3s; }
        .conn-badge.online { border-color: var(--green-glow); color: var(--green-glow); box-shadow: 0 0 10px rgba(0, 255, 135, 0.2); }
        .conn-badge.streaming { border-color: var(--amber-glow); color: var(--amber-glow); box-shadow: 0 0 10px rgba(255, 159, 67, 0.3); }
        .container { width: 95%; max-width: 900px; display: flex; flex-direction: column; gap: 20px; padding-bottom: 40px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 15px; width: 100%; }
        .relay-card { background: var(--card-bg); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 20px; text-align: center; transition: all 0.3s ease; }
        .relay-card i { font-size: 30px; margin-bottom: 10px; display: block; }
        .relay-card span { font-size: 14px; font-weight: 600; opacity: 0.8; }
        .relay-card .status { font-size: 11px; margin-top: 5px; display: block; letter-spacing: 1px; }
        .relay-card.ON { background: rgba(157, 80, 187, 0.2); border-color: var(--purple-main); box-shadow: 0 0 15px rgba(157, 80, 187, 0.3); }
        .relay-card.ON i { color: var(--purple-main); text-shadow: 0 0 10px var(--purple-main); }
        .relay-card.OFF { opacity: 0.6; }
        .audio-monitor-card { background: rgba(157, 80, 187, 0.1); border: 1px dashed var(--purple-main); border-radius: 15px; padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; gap: 15px; margin-bottom: -5px; }
        .audio-monitor-card span { font-size: 13px; font-weight: 600; color: #ff9f43; }
        .voice-settings { display: flex; align-items: center; gap: 10px; }
        .btn-voice { background: #00ff87; color: #000; border: none; padding: 6px 14px; border-radius: 20px; font-weight: bold; cursor: pointer; font-size: 12px; }
        .chat-card { background: var(--card-bg); border-radius: 25px; border: 1px solid rgba(255,255,255,0.1); display: flex; flex-direction: column; height: 430px; overflow: hidden; }
        .chat-window { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
        .msg { max-width: 80%; padding: 12px 16px; border-radius: 18px; font-size: 14px; line-height: 1.5; }
        .user-msg { align-self: flex-end; background: var(--purple-main); color: white; border-bottom-right-radius: 4px; }
        .ai-msg { align-self: flex-start; background: rgba(255,255,255,0.1); color: #eee; border-bottom-left-radius: 4px; }
        .system-msg { align-self: center; background: rgba(255, 159, 67, 0.1); color: #ff9f43; border: 1px dashed #ff9f43; font-size: 12px; border-radius: 10px; }
        .input-area { padding: 15px; background: rgba(0,0,0,0.2); display: flex; gap: 10px; }
        .input-area input { flex: 1; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 50px; padding: 12px 20px; color: white; outline: none; font-size: 15px; }
        .input-area input:focus { border-color: var(--purple-main); }
        .input-area button { background: var(--purple-main); color: white; border: none; width: 45px; height: 45px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: 0.3s; }
    </style>
</head>
<body>
    <header><h1>RoomX</h1><div id="conn-status" class="conn-badge"><i class="fas fa-circle"></i> <span id="conn-text">HomeX Disconnected</span></div></header>
    <div class="container">
        <div id="device-grid" class="grid"><div class="relay-card OFF"><span>Loading Sync...</span></div></div>
        <div class="audio-monitor-card"><span><i class="fas fa-volume-high"></i> Dashboard Agent Real Audio Player:</span><div class="voice-settings"><button id="play-btn" class="btn-voice" onclick="playLiveAudio()">▶ Play Voice Response</button></div></div>
        <audio id="dashboard-speaker" style="display:none;"></audio>
        <div class="chat-card">
            <div class="chat-window" id="chat-window"><div class="msg ai-msg">Welcome back Zion! Unified Hub Status System is fully sync'd.</div></div>
            <div class="input-area"><input type="text" id="chat-msg" placeholder="Type a message or command..." onkeypress="handleKeyPress(event)"><button id="send-btn" onclick="sendManualCommand()"><i class="fas fa-paper-plane"></i></button></div>
        </div>
    </div>
    <script>
        const chatWindow = document.getElementById('chat-window'); const dSpk = document.getElementById('dashboard-speaker'); let isSending = false;
        function playLiveAudio() { dSpk.src = "/get-tts-audio?t=" + new Date().getTime(); dSpk.load(); dSpk.play().catch(function(err){}); }
        function updateHub() {
            fetch('{{ fb_url }}').then(res => res.json()).then(data => {
                const grid = document.getElementById('device-grid'); grid.innerHTML = '';
                const devices = [{ id: "relay_1", name: "Main Light", icon: "fa-lightbulb" }, { id: "relay_2", name: "Dim Light", icon: "fa-moon" }, { id: "relay_3", name: "Fan", icon: "fa-fan" }, { id: "relay_4", name: "Socket", icon: "fa-plug" }];
                devices.forEach(function(dev) {
                    const state = data[dev.id] || "OFF"; let spinClass = (state === 'ON' && dev.id === 'relay_3') ? 'fa-spin' : '';
                    grid.innerHTML += '<div class="relay-card ' + state + '"><i class="fas ' + dev.icon + ' ' + spinClass + '"></i><span>' + dev.name + '</span><span class="status">' + state + '</span></div>';
                });
            });
            fetch('/get-latest-events').then(res => res.json()).then(data => {
                const badge = document.getElementById('conn-status'); const text = document.getElementById('conn-text');
                badge.classList.remove('online', 'streaming');
                if(data.state === "Streaming") { badge.classList.add('streaming'); text.innerText = "Voice Transmit Active..."; }
                else if(data.state === "Online") { badge.classList.add('online'); text.innerText = "HomeX Connected to Internet"; }
                else { text.innerText = "HomeX Disconnected"; }
                if (data.new_messages && data.new_messages.length > 0) {
                    data.new_messages.forEach(function(msg) {
                        if(msg.type === 'voice_start') { chatWindow.innerHTML += '<div class="msg system-msg"><i class="fas fa-microphone"></i> Server Processing Incoming Audio...</div>'; }
                        else { chatWindow.innerHTML += '<div class="msg user-msg" style="border: 1px dashed rgba(255,255,255,0.4);"><i class="fas fa-microphone" style="font-size:10px; margin-right:5px;"></i>' + msg.user + '</div><div class="msg ai-msg">' + msg.ai + '</div>'; setTimeout(playLiveAudio, 600); }
                    });
                    chatWindow.scrollTop = chatWindow.scrollHeight;
                }
            });
        }
        function sendManualCommand() {
            const input = document.getElementById('chat-msg'); const btn = document.getElementById('send-btn'); const cmd = input.value.trim(); if(!cmd || isSending) return;
            isSending = true; input.disabled = true; btn.disabled = true; chatWindow.innerHTML += '<div class="msg user-msg">' + cmd + '</div>'; chatWindow.scrollTop = chatWindow.scrollHeight;
            fetch('/voice-command', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ text: cmd }) })
            .then(res => res.json()).then(data => {
                chatWindow.innerHTML += '<div class="msg ai-msg">' + data.reply + '</div>'; chatWindow.scrollTop = chatWindow.scrollHeight;
                setTimeout(playLiveAudio, 400); input.value = ''; input.disabled = false; btn.disabled = false; isSending = false; input.focus(); updateHub();
            }).catch(() => { input.disabled = false; btn.disabled = false; isSending = false; input.focus(); });
        }
        function handleKeyPress(e) { if(e.key === 'Enter') sendManualCommand(); }
        setInterval(updateHub, 1000); updateHub(); document.getElementById('chat-msg').focus();
    </script>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def home():
    return render_template_string(DASHBOARD_TEMPLATE, fb_url=FIREBASE_URL), 200

@app.route('/get-tts-audio', methods=['GET'])
def get_tts_audio():
    global current_tts_audio
    if current_tts_audio is None:
        return jsonify({"error": "No voice yet"}), 404
    return send_file(io.BytesIO(current_tts_audio), mimetype="audio/mpeg")

@app.route('/get-voice-track', methods=['GET'])
def get_voice_track():
    global last_recorded_wav
    if last_recorded_wav is None:
        return jsonify({"error": "No track yet"}), 404
    return send_file(io.BytesIO(last_recorded_wav), mimetype="audio/wav")

@app.route('/get-latest-events', methods=['GET'])
def get_latest_events():
    global ui_pending_messages, last_esp32_seen, esp32_current_state
    if time.time() - last_esp32_seen > 5.0:
        esp32_current_state = "Disconnected"
    messages_to_send = list(ui_pending_messages)
    ui_pending_messages.clear()
    return jsonify({"state": esp32_current_state, "new_messages": messages_to_send})

@app.route('/esp32-ping', methods=['POST'])
def esp32_ping():
    global last_esp32_seen, esp32_current_state
    last_esp32_seen = time.time()
    if esp32_current_state != "Streaming":
        esp32_current_state = "Online"
    return jsonify({"status": "acknowledged"}), 200

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global last_esp32_seen, ui_pending_messages, esp32_current_state
    last_esp32_seen = time.time()
    
    if request.headers.get('Content-Type') == 'application/octet-stream':
        esp32_current_state = "Streaming"
        ui_pending_messages.append({"type": "voice_start"})
        audio_bytes = request.get_data()
        
        if len(audio_bytes) < 2000:
            esp32_current_state = "Online"
            return jsonify({"error": "Audio track too short"}), 400
            
        return transcribe_and_process(audio_bytes)
    else:
        data = request.get_json() or {}
        command_text = data.get("text", "").strip()
        if command_text:
            return process_with_groq(command_text, source="manual")
            
    return jsonify({"error": "Invalid request"}), 400

def transcribe_and_process(audio_bytes):
    global last_recorded_wav
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
        
        last_recorded_wav = header + audio_bytes
        wav_io = io.BytesIO(last_recorded_wav)
        wav_io.name = "audio.wav"

        transcription = groq_client.audio.transcriptions.create(
            file=wav_io,
            model="whisper-large-v3",
            language="en"
        )
        user_text = transcription.text.strip() if transcription.text else ""
        if not user_text or len(user_text) < 2:
            return jsonify({"status": "Ignored", "reason": "Empty transcription"}), 200
            
        return process_with_groq(user_text, source="voice")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def process_with_groq(user_message, source="manual"):
    global chat_history, ui_pending_messages, current_tts_audio
    
    current_relays = {"relay_1": "OFF", "relay_2": "OFF", "relay_3": "OFF", "relay_4": "OFF"}
    try:
        res = requests.get(FIREBASE_URL, timeout=1.5)
        if res.status_code == 200 and res.json(): current_relays = res.json()
    except: pass

    # ১. প্রথম ধাপে রাউটার প্রম্পট: এআই বুঝবে সাধারণ প্রশ্ন নাকি রিলে কন্ট্রোল কমান্ড
    router_instruction = """You are an advanced Smart Home Assistant routing engine.
    Analyze the user message. Is it asking for general world knowledge, calculations, live status, or internet search?
    If YES, response exactly with: {"need_search": "the specific short search term"}
    If NO (it's just a regular home automation control command like 'turn on fan'), response exactly with: {"need_search": "NO"}"""
    
    search_query = "NO"
    try:
        route_check = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": router_instruction}, {"role": "user", "content": user_message}],
            response_format={"type": "json_object"}
        )
        route_res = json.loads(route_check.choices[0].message.content)
        search_query = route_res.get("need_search", "NO")
    except: pass

    # ২. যদি লাইভ ইনফরমেশন লাগে, তবে ব্যাকগ্রাউন্ডে ইন্টারনেট স্ক্র্যাপ হবে
    internet_context = ""
    if search_query != "NO":
        print(f"🌐 Fetching live data from internet for: {search_query}")
        internet_context = internet_search(search_query)

    # ৩. ফাইনাল প্রম্পট জেনারেশন (হোম অটোমেশন কন্ট্রোল + লাইভ ইন্টারনেট কনটেক্সট কম্বিনেশন)
    system_instruction = f"""You are RoomX Advanced Intelligence Hub, fully integrated with smart home controls and world knowledge.
    Smart Home Mapping: r1:Main Light, r2:Dim Light, r3:Fan, r4:Socket.
    Current Home Relay States: {json.dumps(current_relays)}
    
    LIVE INTERNET SEARCH CONTEXT (Use this if user asks for factual info/updates/news):
    ---
    {internet_context}
    ---
    
    Rules:
    1. If user asks general questions or live data, formulate a helpful, concise answer based on the search context or your training data.
    2. If user requests to toggle relays, update the states accordingly while preserving all other untouched states.
    3. Output JSON ONLY. Scheme: {{"reply": "your crisp vocal answer here", "relays": {{"relay_1": "ON/OFF", "relay_2": "ON/OFF", "relay_3": "ON/OFF", "relay_4": "ON/OFF"}}}}"""

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
        ai_reply = result.get("reply", "Command executed successfully.")
        updates = result.get("relays", current_relays)
        
        # ফায়ারবেস রিলে স্ট্যাটাস সিঙ্ক
        requests.patch(FIREBASE_URL, json=updates, timeout=1.5)
        
        chat_history.append({"user": user_message, "ai": ai_reply})
        if len(chat_history) > MAX_HISTORY_LENGTH: chat_history.pop(0)
        
        # গুগল টিটিএস এর অডিও জেনারেশন
        tts = gTTS(text=ai_reply, lang='en', slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        current_tts_audio = fp.getvalue() 
        
        if source == "voice":
            ui_pending_messages.append({"user": user_message, "ai": ai_reply})
            
        return jsonify({"status": "Success", "reply": ai_reply}), 200
    except Exception as e:
        return jsonify({"status": "Hub Error", "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
