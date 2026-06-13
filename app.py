import os
import json
import time
from flask import Flask, request, jsonify, render_template_string, send_file
from groq import Groq
import requests
import io

app = Flask(__name__)

# Groq Configuration
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
FIREBASE_URL = "https://homebymmzion-default-rtdb.firebaseio.com/devices.json"

# Global System States
last_recorded_wav = None
chat_history = []
MAX_HISTORY_LENGTH = 5 
last_esp32_seen = 0  
esp32_current_state = "Disconnected" # Disconnected, Online, Streaming
ui_pending_messages = []

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
            --amber-glow: #ff9f43;
            --red-glow: #ff2e63;
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body { 
            font-family: 'Segoe UI', sans-serif; 
            background: var(--bg); 
            background-image: radial-gradient(circle at 50% 50%, #1a1a3a 0%, #0f0c29 100%);
            color: var(--text); margin: 0; padding: 0;
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
            background: rgba(0,0,0,0.4); border: 1px solid var(--red-glow); color: var(--red-glow);
            padding: 6px 14px; border-radius: 50px; font-size: 12px; font-weight: 600;
            display: flex; align-items: center; gap: 8px; transition: 0.3s;
        }
        .conn-badge.online {
            border-color: var(--green-glow); color: var(--green-glow);
            box-shadow: 0 0 10px rgba(0, 255, 135, 0.2);
        }
        .conn-badge.streaming {
            border-color: var(--amber-glow); color: var(--amber-glow);
            box-shadow: 0 0 10px rgba(255, 159, 67, 0.3);
        }
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
        
        .audio-monitor-card {
            background: rgba(157, 80, 187, 0.1); border: 1px dashed var(--purple-main);
            border-radius: 15px; padding: 12px 20px; display: flex; align-items: center;
            justify-content: space-between; gap: 15px; margin-bottom: -5px;
        }
        .audio-monitor-card span
