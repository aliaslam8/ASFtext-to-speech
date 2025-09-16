from flask import Flask, render_template, request, send_file, jsonify
from flask_cors import CORS
import base64, io, os, time, requests
from pydub import AudioSegment
from pydub.effects import normalize
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from key_manager import KeyManager

# Load .env
load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

API_BASE = "https://api.sws.speechify.com/v1/audio/speech"
MAX_CHARS = 2000
MAX_WORKERS = 5
SLEEP_PER_CHUNK = 0.3

# Admin Password
KEY_UPLOAD_PASSWORD = os.getenv("ADMIN_PASSWORD", "4444")

# Load API Keys
API_KEYS = []
for i in range(1, 101):
    k = os.getenv(f"API_KEY_{i}")
    if k:
        API_KEYS.append(k.strip('"'))

key_manager = KeyManager(limit=50000)
if API_KEYS:
    key_manager.load_keys(API_KEYS)
else:
    print("⚠️ No keys found in .env")


# ----------------- Fetch audio one chunk -----------------
def fetch_chunk_audio(chunk: str, voice_id: str, emotion: str, chunk_index: int) -> AudioSegment:
    last_error = None
    for api in list(key_manager.keys):
        api_key = api["key"]

        for attempt in range(3):
            try:
                ssml_extra = f"<emotions value='{emotion}'>" if emotion else ""
                ssml_text = f"<speak>{ssml_extra}{chunk}{'</emotions>' if emotion else ''}</speak>"

                payload = {"input": ssml_text, "voice_id": voice_id, "audio_format": "wav"}
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

                r = requests.post(API_BASE, headers=headers, json=payload, timeout=30)

                if r.status_code == 402:
                    print(f"❌ Key {api_key[:8]} exhausted, skipping")
                    key_manager.deactivate_key(api_key)
                    break

                if r.status_code == 503:
                    wait_time = 2 ** attempt
                    print(f"⚠️ 503 {api_key[:8]} retry in {wait_time}s (attempt {attempt+1})")
                    time.sleep(wait_time)
                    continue

                r.raise_for_status()
                data = r.json()
                if "audio_data" not in data or not data["audio_data"]:
                    raise Exception("No audio_data returned")

                audio_bytes = base64.b64decode(data["audio_data"])
                time.sleep(SLEEP_PER_CHUNK)
                audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")
                print(f"✅ Chunk {chunk_index} OK with {api_key[:8]}..., len={len(audio)/1000:.2f}s")
                return audio

            except Exception as e:
                last_error = str(e)
                print(f"⚠️ Key {api_key[:8]} attempt {attempt+1} failed: {last_error}")
                time.sleep(1)

        print(f"➡️ Skipping key {api_key[:8]} after repeated failures")

    raise Exception(f"All keys failed for chunk {chunk_index}. Last error: {last_error or 'No API responded'}")


# ----------------- Routes -----------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/speak", methods=["POST"])
def speak():
    text = request.form.get("text", "").strip()
    voice_id = request.form.get("voice_id", "").strip()
    file_name = request.form.get("file_name", "speech").strip()
    emotion = request.form.get("emotion", "").strip()
    bitrate = request.form.get("bitrate", "192k")

    if not key_manager.active_keys_left():
        return jsonify({"status": "error", "message": "❌ No valid keys"}), 403
    if not text:
        return jsonify({"status": "error", "message": "❌ No text"}), 400

    # Split text
    parts = [text[i:i+MAX_CHARS] for i in range(0, len(text), MAX_CHARS)]
    final_audio = AudioSegment.silent(duration=0)

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(
                lambda tup: fetch_chunk_audio(tup[1], voice_id, emotion, tup[0]+1),
                enumerate(parts)
            ))
            for r in results:
                final_audio += r
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

    # 🎚️ Normalize + Boost
    final_audio = normalize(final_audio)
    final_audio = final_audio + 4   # Boost by +4dB

    # Export MP3
    final_audio = final_audio.set_channels(1)
    buf = io.BytesIO()
    final_audio.export(buf, format="mp3", bitrate=bitrate, parameters=["-ar","44100"])  # CD quality sample rate
    buf_size = buf.getbuffer().nbytes
    print(f"🎧 Final MP3 length = {len(final_audio)/1000:.2f}s, size={buf_size/1024:.1f} KB")

    if buf_size == 0:
        return jsonify({"status": "error", "message": "Empty MP3"}), 500

    buf.seek(0)
    return send_file(buf, mimetype="audio/mpeg", as_attachment=False, download_name=f"{file_name}.mp3")


# -------- Admin Key Management --------
@app.route("/check_password", methods=["POST"])
def check_password():
    data = request.get_json()
    if not data or data.get("password") != KEY_UPLOAD_PASSWORD:
        return jsonify({"status": "error"}), 403
    return jsonify({"status": "ok"})


@app.route("/add_key", methods=["POST"])
def add_key():
    data = request.get_json()
    if not data or data.get("password") != KEY_UPLOAD_PASSWORD:
        return jsonify({"status": "error"}), 403
    new_key = data.get("key", "").strip()
    if new_key:
        key_manager.add_key(new_key)
        return jsonify({"status": "ok", "total_keys": key_manager.count()})
    return jsonify({"status": "error", "message": "No key provided"}), 400


@app.route("/delete_key", methods=["POST"])
def delete_key():
    data = request.get_json()
    if not data or data.get("password") != KEY_UPLOAD_PASSWORD:
        return jsonify({"status": "error"}), 403
    removed = key_manager.delete_first_key()
    return jsonify({"status": "ok", "deleted": bool(removed), "total": key_manager.count()})


if __name__ == "__main__":
    print("🚀 Flask server running at http://127.0.0.1:5000")
    app.run(debug=True, threaded=True)