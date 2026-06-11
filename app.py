import os
import json
import time
import io
import requests
from flask import Flask, request, jsonify, render_template_string

app = Flask(__name__)
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

chat_history = []
MAX_HISTORY_LENGTH = 7 
last_esp32_seen = 0  
esp32_current_state = "Disconnected" 
ui_pending_messages = []

def internet_search(query):
    try:
        url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1"
        res = requests.get(url, timeout=2.5)
        if res.status_code == 200 and res.json().get("AbstractText"):
            return res.json()["AbstractText"]
        return "No direct context found."
    except: return "Search timeout."

# (ড্যাশবোর্ড HTML টেমপ্লেট হুবহু অপরিবর্তিত থাকবে)
DASHBOARD_TEMPLATE = """...""" # তোমার অরিজিনাল UI কোড এখানে বসবে

@app.route('/', methods=['GET'])
def home(): 
    return "RoomX Hybrid Radio Node Active", 200

@app.route('/get-latest-events', methods=['GET'])
def get_latest_events():
    global ui_pending_messages, last_esp32_seen, esp32_current_state
    if time.time() - last_esp32_seen > 6.0: esp32_current_state = "Disconnected"
    messages_to_send = list(ui_pending_messages)
    ui_pending_messages.clear()
    return jsonify({"state": esp32_current_state, "new_messages": messages_to_send})

@app.route('/esp32-ping', methods=['POST'])
def esp32_ping():
    global last_esp32_seen; last_esp32_seen = time.time()
    return jsonify({"status": "acknowledged"}), 200

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global last_esp32_seen, ui_pending_messages, esp32_current_state
    last_esp32_seen = time.time()
    
    if request.headers.get('Content-Type') != 'application/octet-stream':
        return jsonify({"error": "Bad Request"}), 400
        
    audio_bytes = request.get_data()
    duration = len(audio_bytes)
    
    header = bytearray(44)
    header[0:4] = b'RIFF'; header[4:8] = (duration + 36).to_bytes(4, 'little'); header[8:12] = b'WAVE'
    header[12:16] = b'fmt '; header[16:20] = (16).to_bytes(4, 'little'); header[20:22] = (1).to_bytes(2, 'little')
    header[22:24] = (1).to_bytes(2, 'little'); header[24:28] = (16000).to_bytes(4, 'little')
    header[28:32] = (32000).to_bytes(4, 'little'); header[32:34] = (2).to_bytes(2, 'little')
    header[34:36] = (16).to_bytes(2, 'little'); header[36:40] = b'data'; header[40:44] = duration.to_bytes(4, 'little')
    
    try:
        transcription = groq_client.audio.transcriptions.create(file=io.BytesIO(header + audio_bytes), model="whisper-large-v3")
        user_text = transcription.text.strip()
        
        # Groq প্রসেসিং ও ফায়ারবেস আপডেট
        current_relays = {"relay_1": "OFF", "relay_2": "OFF", "relay_3": "OFF", "relay_4": "OFF"}
        # (এখানে আগের মতো Groq কল ও Patch মেকানিজম থাকবে)
        
        # UI মেসেজ পুশ
        ui_pending_messages.append({"user": user_text, "ai": "Command Executed. Radio Stream Triggered."})
        
        return jsonify({"status": "Success"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
