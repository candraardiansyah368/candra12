document.addEventListener("DOMContentLoaded", () => {
    const video = document.getElementById("video");
    const canvas = document.getElementById("canvas");
    const ctx = canvas.getContext("2d", { alpha: false });
    const statusText = document.getElementById("status-text");
    const statusCard = document.getElementById("status");
    const frame = document.getElementById("frame");
    const nikInput = document.getElementById("nik");
    const scanBtn = document.getElementById("scan");
    const switchBtn = document.getElementById("switchCamera");
    const torchBtn = document.getElementById("torch");
    const searchBtn = document.getElementById("search");

    let stream = null, track = null;
    let facing = "environment", torch = false, scanning = false, busy = false;
    let lastNik = "", stableCount = 0;

    async function startCamera() {
        if(stream) stream.getTracks().forEach(t => t.stop());
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 720 } }
            });
            video.srcObject = stream;
            await video.play();
            track = stream.getVideoTracks()[0];
            
            enableFocus();
            checkTorch();
            updateStatus("Kamera siap. Sentuh layar untuk fokus.", "ℹ️");
        } catch(error) {
            updateStatus("Akses kamera diblokir.", "⚠️");
        }
    }

    async function enableFocus() {
        if(!track || !track.getCapabilities) return;
        const cap = track.getCapabilities();
        if(cap.focusMode) {
            try { 
                await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] }); 
            } catch(e) {}
        }
    }

    // Tap to focus manual
    video.onclick = async () => {
        if(track && track.getCapabilities) {
            const cap = track.getCapabilities();
            if(cap.focusMode) {
                try {
                    await track.applyConstraints({ advanced: [{ focusMode: "single-shot" }] });
                    updateStatus("Menyesuaikan fokus...", "🎯");
                    setTimeout(enableFocus, 1000);
                } catch(e) {}
            }
        }
    };

    function checkTorch() {
        if(track && track.getCapabilities) {
            let cap = track.getCapabilities();
            torchBtn.style.display = cap.torch ? "flex" : "none";
        }
    }

    switchBtn.onclick = () => {
        facing = facing === "environment" ? "user" : "environment";
        startCamera();
    };

    torchBtn.onclick = async () => {
        if(!track) return;
        torch = !torch;
        try {
            await track.applyConstraints({ advanced: [{ torch: torch }] });
            torchBtn.style.background = torch ? "#e2e8f0" : "white";
        } catch(e) {}
    };

    function updateStatus(text, icon) {
        statusText.innerText = text;
        statusCard.querySelector(".status-icon").innerText = icon;
    }

    async function captureFrame() {
        return new Promise((resolve) => {
            if(!video.videoWidth) { resolve(null); return; }
            let scale = 640 / video.videoWidth; 
            canvas.width = Math.floor(video.videoWidth * scale);
            canvas.height = Math.floor(video.videoHeight * scale);
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            canvas.toBlob(resolve, "image/jpeg", 0.7);
        });
    }

    async function scanEngine() {
        if(!scanning) return;
        if(busy) return;

        busy = true;
        try {
            let image = await captureFrame();
            if(image) {
                let form = new FormData();
                form.append("image", image, "ktp.jpg");

                let response = await fetch("/api/ocr-nik", { method: "POST", body: form });
                let data = await response.json();

                if(data.nik) {
                    nikInput.value = data.nik;
                    searchBtn.style.display = "block";

                    if(lastNik === data.nik) stableCount++;
                    else { lastNik = data.nik; stableCount = 1; }

                    updateStatus(`Mendeteksi NIK... (${data.confidence}%)`, "🔍");

                    if(data.reliable && stableCount >= 2) {
                        scanning = false;
                        updateStatus("NIK Berhasil Direkam!", "✅");
                        statusCard.style.borderColor = "#10b981";
                        statusCard.style.backgroundColor = "#dcfce7";
                        frame.classList.remove("active");
                        scanBtn.innerHTML = "↺ Ulangi Scan";
                        scanBtn.classList.replace("btn-primary", "btn-outline");
                    }
                }
            }
        } catch(error) { 
            console.log("Tertunda, mengulangi..."); 
        } finally {
            busy = false;
            if(scanning) setTimeout(scanEngine, 50);
        }
    }

    scanBtn.onclick = () => {
        scanning = !scanning;
        if(scanning) {
            stableCount = 0; 
            lastNik = ""; 
            nikInput.value = "";
            searchBtn.style.display = "none";
            frame.classList.add("active");
            scanBtn.innerHTML = "⏹ Berhenti Scan";
            scanBtn.classList.replace("btn-outline", "btn-primary");
            statusCard.style.borderColor = "#e2e8f0";
            statusCard.style.backgroundColor = "#ffffff";
            updateStatus("Memindai KTP...", "⏳");
            scanEngine();
        } else {
            frame.classList.remove("active");
            scanBtn.innerHTML = "▶ Mulai Scan KTP";
            updateStatus("Pemindaian dihentikan.", "ℹ️");
        }
    };

    nikInput.addEventListener("input", function() {
        this.value = this.value.replace(/\D/g, "").slice(0, 16);
        searchBtn.style.display = this.value.length === 16 ? "block" : "none";
    });

    searchBtn.onclick = async () => {
        let nik = nikInput.value.trim();
        if(nik.length !== 16) return alert("NIK harus 16 digit!");
        
        searchBtn.innerHTML = "⏳ Memeriksa ke Server...";
        searchBtn.disabled = true;

        try {
            let response = await fetch("/api/search-nik", {
                method:"POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ nik: nik })
            });
            let data = await response.json();
            updateStatus(data.message, "📄");
            statusCard.style.backgroundColor = "#e0f2fe";
            statusCard.style.borderColor = "#bae6fd";
        } catch(error) {
            updateStatus("Koneksi ke server SIPBPNT gagal.", "❌");
        } finally {
            searchBtn.innerHTML = "🔍 Cek Database SIPBPNT";
            searchBtn.disabled = false;
        }
    };

    startCamera();
});