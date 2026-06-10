import os
import json
import base64
import numpy as np
from flask import Flask, request, jsonify
from google import genai
from google.genai import types
import requests

app = Flask(__name__)

# জেমিনি ক্লায়েন্ট কনফিগারেশন
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

# সার্ভার মেমরিতে অডিও বাফার এবং স্টেট ট্র্যাকিং
audio_buffer = bytearray()
SILENCE_THRESHOLD = 500  # আপনার মাইক্রোফোনের নয়েজ লেভেল অনুযায়ী এটি পরিবর্তন করতে পারেন (PCM Amplitude)
SILENCE_DURATION_CHUNKS = 15  # পরপর কতগুলো চঙ্ক নীরব থাকলে ধরে নেওয়া হবে কথা শেষ (প্রায় ১.৫ থেকে ২ সেকেন্ড)
silent_chunks_count = 0
has_speech_started = False

@app.route('/', methods=['GET'])
def health_check():
    """cron-job.org এর জন্য হেলথ চেক রুট (404 এরর দূর করার জন্য)"""
    return "Smart Home Server is running smoothly!", 200

@app.route('/voice-command', methods=['POST'])
def handle_command():
    global audio_buffer, silent_chunks_count, has_speech_started
    
    data = request.get_json()
    audio_base64 = data.get("audio", None)
    command_text = data.get("text", "")
    
    # ১. সরাসরি টেক্সট কমান্ড আসলে (টেস্টিং বা প্যানেলের জন্য)
    if command_text and not audio_base64:
        return process_with_gemini(command_text, is_audio=False)
        
    # ২. অনবরত অডিও স্ট্রিম হ্যান্ডেল করা (ESP32 থেকে আসা Chunks)
    if audio_base64:
        chunk_bytes = base64.b64decode(audio_base64)
        
        # সার্ভার লেভেলে ভলিউম/এনার্জি অ্যানালাইসিস (ESP32 এর ওপর চাপ কমানোর জন্য)
        # ধরি ওয়ান-চ্যানেল ১৬-বিট পিসিএম অডিও আসছে
        audio_data = np.frombuffer(chunk_bytes, dtype=np.int16)
        
        if len(audio_data) > 0:
            amplitude = np.max(np.abs(audio_data))
            
            if amplitude > SILENCE_THRESHOLD:
                # শব্দ সনাক্ত হয়েছে, বাফারে যোগ করো
                audio_buffer.extend(chunk_bytes)
                silent_chunks_count = 0
                has_speech_started = True
            else:
                # নীরবতা বা সাধারণ নয়েজ
                if has_speech_started:
                    audio_buffer.extend(chunk_bytes) # কথার মাঝখানের পজ বা ছোট বিরতি ধরে রাখা
                    silent_chunks_count += 1
        
        # ব্যবহারকারী কথা বলা শেষ করেছেন কিনা তা সার্ভার নিজে সিদ্ধান্ত নেবে
        if has_speech_started and silent_chunks_count >= SILENCE_DURATION_CHUNKS:
            full_audio = bytes(audio_buffer)
            
            # স্টেট রিসেট (পরবর্তী কমান্ডের জন্য মেমরি খালি করা)
            audio_buffer = bytearray()
            silent_chunks_count = 0
            has_speech_started = False
            
            # জেমিনিকে কল করার জন্য ফাইনাল প্রসেসিং
            print("Speech ended. Sending accumulated audio to Gemini...")
            return process_with_gemini(full_audio, is_audio=True)
            
        return jsonify({"status": "Streaming", "listening": has_speech_started}), 200

    return jsonify({"error": "No valid input found"}), 400


def process_with_gemini(contents_data, is_audio=False):
    """জেমিনি এপিআই কল এবং ফায়ারবেস আপডেট করার সেন্ট্রাল ফাংশন"""
    contents = []
    
    if is_audio:
        contents.append({
            "inline_data": {
                "mime_type": "audio/wav", 
                "data": contents_data
            }
        })
    else:
        contents.append(contents_data)

    system_instruction = """You are an AI Smart Home Assistant. 
    Analyze the input and return ONLY a JSON object for relays: 
    {"relay_1": "ON/OFF", "relay_2": "ON/OFF", "relay_3": "ON/OFF", "relay_4": "ON/OFF"}"""
    
    try:
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
        return jsonify({"status": "Success", "updates": updates}), 200
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
