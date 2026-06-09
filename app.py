import os
import json
import base64
from flask import Flask, request, jsonify
from google import genai
from google.genai import types
import requests

app = Flask(__name__)
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

@app.route('/voice-command', methods=['POST'])
def handle_command():
    data = request.get_json()
    
    # ইনপুট হিসেবে টেক্সট না অডিও তা চেক করা
    audio_base64 = data.get("audio", None)
    command_text = data.get("text", "")
    
    contents = []
    
    if audio_base64:
        # অডিও থাকলে সেটাকে বাইনারিতে রূপান্তর করা
        audio_bytes = base64.b64decode(audio_base64)
        contents.append({
            "inline_data": {
                "mime_type": "audio/wav", 
                "data": audio_bytes
            }
        })
    elif command_text:
        contents.append(command_text)
    else:
        return jsonify({"error": "No input found"}), 400

    system_instruction = """You are an AI Smart Home Assistant. 
    Analyze the input and return ONLY a JSON object for relays: 
    {"relay_1": "ON/OFF", "relay_2": "ON/OFF", "relay_3": "ON/OFF", "relay_4": "ON/OFF"}"""
    
    try:
        # জেমিনি এপিআই কল (অডিও বা টেক্সট উভয়ই হ্যান্ডেল করবে)
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            )
        )
        
        updates = json.loads(response.text)
        requests.patch(FIREBASE_URL, json=updates)
        return jsonify({"status": "Success", "updates": updates})
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
