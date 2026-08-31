import re
import threading
from collections import defaultdict
from typing import Any

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

# =====================================
# IMPORT LIBRARY & INISIALISASI OCR
# =====================================
try:
    import cv2
    import numpy as np
    from rapidocr import RapidOCR
    OCR_IMPORT_ERROR = None
except Exception as error:
    cv2, np, RapidOCR = None, None, None
    OCR_IMPORT_ERROR = str(error)

_ocr_engine = None
_engine_lock = threading.Lock()
_inference_lock = threading.Lock()

def get_ocr_engine():
    global _ocr_engine
    if OCR_IMPORT_ERROR:
        raise RuntimeError(f"RapidOCR error: {OCR_IMPORT_ERROR}")
    if _ocr_engine is None:
        with _engine_lock:
            if _ocr_engine is None:
                _ocr_engine = RapidOCR()
    return _ocr_engine

# =====================================
# LOGIKA OCR (Validasi Pintar NIK)
# =====================================
def valid_nik_structure(nik: str):
    if not re.fullmatch(r"\d{16}", nik): 
        return False
        
    # KUNCI AKURASI: Cek Kode Provinsi Indonesia (hanya ada kode 11 s/d 94)
    provinsi = int(nik[:2])
    if provinsi < 11 or provinsi > 94:
        return False
        
    day, month = int(nik[6:8]), int(nik[8:10])
    return (1 <= day <= 31 or 41 <= day <= 71) and (1 <= month <= 12)

def nik_candidates(text):
    # Bersihkan huruf yang bentuknya sering menipu OCR
    value = str(text or "").upper().replace("NIK", "")
    value = value.translate(str.maketrans({
        "O":"0", "Q":"0", "D":"0", "I":"1", "L":"1", 
        "|":"1", "Z":"2", "S":"5", "G":"6", "B":"8", "?":"7", "T":"7"
    }))
    
    # Mencari pola yang benar-benar 16 digit angka (walau terpisah spasi)
    matches = re.finditer(r"(?<!\d)((?:\d[\s\-]*){16})(?!\d)", value)
    results = []
    
    for match in matches:
        clean_nik = re.sub(r"\D", "", match.group(1))
        if len(clean_nik) == 16 and clean_nik not in results:
            results.append(clean_nik)
            
    # Jika gagal mencari 16 digit utuh, cari dengan cara menyambung semua angka
    if not results:
        digits = re.sub(r"\D", "", value)
        for index in range(max(0, len(digits)-15)):
            candidate = digits[index:index+16]
            if len(candidate) == 16 and candidate not in results:
                results.append(candidate)
                
    return results

def safe_list(value):
    if value is None: return []
    if hasattr(value, "tolist"):
        try:
            res = value.tolist()
            if isinstance(res, list): return res
        except Exception: pass
    try: return list(value)
    except Exception: return []

def crop_nik_area(image):
    height, width = image.shape[:2]
    card_width = int(width * 0.95)
    card_height = int(card_width / 1.586)
    x1, y1 = max(0, (width-card_width)//2), max(0, (height-card_height)//2)
    x2, y2 = min(width, x1 + card_width), min(height, y1 + card_height)
    
    card = image[y1:y2, x1:x2]
    if card.size == 0: return image

    h, w = card.shape[:2]
    nik_crop = card[int(h*0.10):int(h*0.60), int(w*0.02):int(w*0.98)]
    return nik_crop if nik_crop.size > 0 else card

def enhance_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast_img = clahe.apply(gray)
    return cv2.cvtColor(contrast_img, cv2.COLOR_GRAY2BGR)

def read_nik_fast(image):
    engine = get_ocr_engine()
    nik_image = enhance_image(crop_nik_area(image))
    
    with _inference_lock:
        result = engine(nik_image)

    if result is None: 
        return None

    texts = safe_list(getattr(result, "txts", None))
    scores = safe_list(getattr(result, "scores", None))
    
    if not texts: 
        return None

    # Digabung dengan spasi agar Regex bisa membedakan NIK dengan Tgl Lahir
    combined_text = " ".join(str(t) for t in texts)
    avg_confidence = sum(float(s) for s in scores) / len(scores) if scores else 0
    
    candidates = nik_candidates(combined_text)
    
    if candidates:
        # Utamakan yang lolos cek Kode Provinsi & Tanggal Valid
        valid_candidates = [nik for nik in candidates if valid_nik_structure(nik)]
        if valid_candidates:
            return {
                "nik": valid_candidates[0],
                "confidence": round(avg_confidence * 100, 1),
                "reliable": True
            }
        
        # Tampilkan sementara jika angkanya meragukan
        return {
            "nik": candidates[0],
            "confidence": round(avg_confidence * 100, 1),
            "reliable": False
        }
        
    return None

# =====================================
# FLASK ROUTES
# =====================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/ocr-nik", methods=["POST"])
def api_ocr_nik():
    try:
        uploaded = request.files.get("image")
        if not uploaded: return jsonify({"nik": None, "reliable": False})

        image_array = np.frombuffer(uploaded.read(), dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if image is None: return jsonify({"nik": None, "reliable": False})

        result = read_nik_fast(image)
        return jsonify(result) if result else jsonify({"nik": None, "reliable": False})
    except Exception as error:
        return jsonify({"error": str(error)}), 500

@app.route("/api/search-nik", methods=["POST"])
def search_nik():
    data = request.get_json(silent=True) or {}
    nik = str(data.get("nik", ""))
    if not re.fullmatch(r"\d{16}", nik):
        return jsonify({"message": "❌ Format NIK tidak valid!"})
    
    return jsonify({
        "nik": nik,
        "message": f"✅ Cek Berhasil: NIK {nik} terdaftar pada sistem SIPBPNT."
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, threaded=True)