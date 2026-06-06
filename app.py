import os
import json
import requests
from flask import Flask, request, jsonify
from google import genai
from google.genai import types

app = Flask(__name__)

# জেমিনির ৩.৫ ফ্ল্যাশ মডেলের জন্য কনফিগারেশন
# সার্ভারে এনভায়রনমেন্ট ভেরিয়েবল হিসেবে GEMINI_API_KEY সেট করতে হবে
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# আপনার ফায়ারবেস রিয়েলটাইম ডেটাবেসের লিংক
# অবশ্যই শেষে .json থাকতে হবে
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

@app.route('/voice-command', methods=['POST'])
def handle_command():
    data = request.get_json()
    command = data.get("text", "")
    
    if not command:
        return jsonify({"error": "No command found"}), 400
        
    # স্মার্ট হোম ডিভাইসের ম্যাপিং সহ সিস্টেম ইন্সট্রাকশন
    system_instruction = """
    You are an AI Smart Home Assistant. 
    Analyze the user's command and return ONLY a valid JSON object updating the relays.
    Map the devices as follows:
    - relay_1: Main Light
    - relay_2: Dim Light
    - relay_3: Fan
    - relay_4: Socket
    States must be "ON" or "OFF".
    Example: If the user says "Turn on main light and fan", respond: {"relay_1": "ON", "relay_3": "ON"}
    """
    
    try:
        # জেমিনি এপিআই কল
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=command,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
            )
        )
        
        # জেমিনির দেওয়া JSON ডেটা পার্স করা
        updates = json.loads(response.text)
        
        # ফায়ারবেসে ডেটা আপডেট করা (PATCH ব্যবহার করে নির্দিষ্ট রিলে আপডেট হবে)
        fb_response = requests.patch(FIREBASE_URL, json=updates)
        
        if fb_response.status_code == 200:
            return jsonify({"status": "Success", "firebase_updated": updates})
        else:
            return jsonify({"error": "Firebase update failed"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
