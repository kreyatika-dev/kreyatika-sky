/* -------------------------------------------------------------
 * KREYATIKA SKY - FRONTEND LOGIC & REAL-TIME API SYNC
 * ------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
    // Initialize Lucide Icons
    lucide.createIcons();

    // Elements Selectors
    const liveClock = document.getElementById("liveClock");
    
    // Sidebar Elements
    const settingsSidebar = document.getElementById("settingsSidebar");
    const toggleSettingsSidebarBtn = document.getElementById("toggleSettingsSidebarBtn");
    const closeSettingsBtn = document.getElementById("closeSettingsBtn");
    
    // Settings Controls
    const sliderCountingLine = document.getElementById("sliderCountingLine");
    const valCountingLine = document.getElementById("valCountingLine");
    const sliderConfidence = document.getElementById("sliderConfidence");
    const valConfidence = document.getElementById("valConfidence");
    const sliderAiFps = document.getElementById("sliderAiFps");
    const valAiFps = document.getElementById("valAiFps");
    const sliderDisplayFps = document.getElementById("sliderDisplayFps");
    const valDisplayFps = document.getElementById("valDisplayFps");
    
    const selectYoloModel = document.getElementById("selectYoloModel");
    const modelSwitchStatus = document.getElementById("modelSwitchStatus");
    const btnRestartEngine = document.getElementById("btnRestartEngine");
    const btnClearStats = document.getElementById("btnClearStats");
    const btnOrientVertical = document.getElementById("btnOrientVertical");
    const btnOrientHorizontal = document.getElementById("btnOrientHorizontal");

    const chkCars = document.getElementById("chkCars");
    const chkMotos = document.getElementById("chkMotos");
    const chkPersons = document.getElementById("chkPersons");
    const chkOverlays = document.getElementById("chkOverlays");
    
    // System Performance elements
    const cpuPercentVal = document.getElementById("cpuPercentVal");
    const cpuProgressFill = document.getElementById("cpuProgressFill");
    const liveFpsVal = document.getElementById("liveFpsVal");
    const yoloLatencyVal = document.getElementById("yoloLatencyVal");
    
    // Live Stream Elements
    const videoStreamImage = document.getElementById("videoStreamImage");
    const videoStreamErrorAlert = document.getElementById("videoStreamErrorAlert");
    
    // Dashboard Counters
    const countCarsVal = document.getElementById("countCarsVal");
    const countMotosVal = document.getElementById("countMotosVal");
    const countPersonsVal = document.getElementById("countPersonsVal");
    const btnInterval30m = document.getElementById("btnInterval30m");
    const btnIntervalToday = document.getElementById("btnIntervalToday");
    const activeCameraName = document.getElementById("activeCameraName");
    
    // Chart Toggles
    const toggleChartRealtime = document.getElementById("toggleChartRealtime");
    const toggleChartTrends = document.getElementById("toggleChartTrends");
    
    // Camera Modal & Grid Elements
    const camerasGridList = document.getElementById("camerasGridList");
    const openAddCameraModalBtn = document.getElementById("openAddCameraModalBtn");
    const addCameraModal = document.getElementById("addCameraModal");
    const closeAddCameraModalBtn = document.getElementById("closeAddCameraModalBtn");
    const cancelAddCameraBtn = document.getElementById("cancelAddCameraBtn");
    const addCameraForm = document.getElementById("addCameraForm");
    
    // Report Generator elements
    const reportStartDate = document.getElementById("reportStartDate");
    const reportEndDate = document.getElementById("reportEndDate");
    const btnGenerateReport = document.getElementById("btnGenerateReport");
    const btnExportCSV = document.getElementById("btnExportCSV");
    const repCarSum = document.getElementById("repCarSum");
    const repMotoSum = document.getElementById("repMotoSum");
    const repPersonSum = document.getElementById("repPersonSum");

    // Global application state
    let statsIntervalMinutes = 30; // Default: show stats for the last 30 minutes
    let activeChartType = 'realtime'; // 'realtime' (30m) or 'trends' (24h)
    let trafficChartInstance = null;
    let pollIntervalId = null;
    let chartPollIntervalId = null;

    // -------------------------------------------------------------
    // 1. LIVE CLOCK INTERFACE
    // -------------------------------------------------------------
    function updateClock() {
        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const secs = String(now.getSeconds()).padStart(2, '0');
        liveClock.textContent = `${hrs}:${mins}:${secs}`;
    }
    setInterval(updateClock, 1000);
    updateClock();

    // -------------------------------------------------------------
    // 2. INTERFACE NAVIGATION & MODALS
    // -------------------------------------------------------------
    toggleSettingsSidebarBtn.addEventListener("click", () => {
        settingsSidebar.classList.add("open");
    });
    
    closeSettingsBtn.addEventListener("click", () => {
        settingsSidebar.classList.remove("open");
    });

    // Camera Modal
    openAddCameraModalBtn.addEventListener("click", () => {
        addCameraModal.classList.add("open");
    });
    
    const closeModal = () => {
        addCameraModal.classList.remove("open");
        addCameraForm.reset();
    };
    
    closeAddCameraModalBtn.addEventListener("click", closeModal);
    cancelAddCameraBtn.addEventListener("click", closeModal);

    // Close on click outside card
    addCameraModal.addEventListener("click", (e) => {
        if (e.target === addCameraModal) closeModal();
    });

    // Stream Disconnect detection
    videoStreamImage.addEventListener("error", () => {
        videoStreamErrorAlert.style.display = "flex";
    });
    
    videoStreamImage.addEventListener("load", () => {
        videoStreamErrorAlert.style.display = "none";
    });

    // -------------------------------------------------------------
    // 3. STATS TAB ACTIONS (30 MIN vs TODAY)
    // -------------------------------------------------------------
    btnInterval30m.addEventListener("click", () => {
        btnInterval30m.classList.add("active");
        btnIntervalToday.classList.remove("active");
        statsIntervalMinutes = 30;
        fetchDashboardStats();
    });

    btnIntervalToday.addEventListener("click", () => {
        btnIntervalToday.classList.add("active");
        btnInterval30m.classList.remove("active");
        statsIntervalMinutes = 1440; // 24 hours (Today counts since midnight loaded dynamically on server)
        fetchDashboardStats();
    });

    // Chart timeline toggles
    toggleChartRealtime.addEventListener("click", () => {
        toggleChartRealtime.classList.add("active");
        toggleChartTrends.classList.remove("active");
        activeChartType = 'realtime';
        fetchChartTimeline();
    });

    toggleChartTrends.addEventListener("click", () => {
        toggleChartTrends.classList.add("active");
        toggleChartRealtime.classList.remove("active");
        activeChartType = 'trends';
        fetchChartTimeline();
    });

    // -------------------------------------------------------------
    // 4. CHART.JS VISUALISATION SYSTEM
    // -------------------------------------------------------------
    function setupChart() {
        const ctx = document.getElementById("trafficChart").getContext("2d");
        
        // Define clean neon gradient colors
        const carGlow = ctx.createLinearGradient(0, 0, 0, 150);
        carGlow.addColorStop(0, 'rgba(0, 242, 254, 0.25)');
        carGlow.addColorStop(1, 'rgba(0, 242, 254, 0.00)');

        const motoGlow = ctx.createLinearGradient(0, 0, 0, 150);
        motoGlow.addColorStop(0, 'rgba(225, 0, 255, 0.25)');
        motoGlow.addColorStop(1, 'rgba(225, 0, 255, 0.00)');

        const personGlow = ctx.createLinearGradient(0, 0, 0, 150);
        personGlow.addColorStop(0, 'rgba(0, 255, 135, 0.25)');
        personGlow.addColorStop(1, 'rgba(0, 255, 135, 0.00)');

        const chartConfig = {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Voitures',
                        data: [],
                        borderColor: '#00f2fe',
                        backgroundColor: carGlow,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 1,
                        pointHoverRadius: 5
                    },
                    {
                        label: 'Motos',
                        data: [],
                        borderColor: '#e100ff',
                        backgroundColor: motoGlow,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 1,
                        pointHoverRadius: 5
                    },
                    {
                        label: 'Piétons',
                        data: [],
                        borderColor: '#00ff87',
                        backgroundColor: personGlow,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.4,
                        pointRadius: 1,
                        pointHoverRadius: 5
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false // Manage legends manually if desired to save layout space
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        padding: 10,
                        backgroundColor: 'rgba(10, 12, 30, 0.95)',
                        titleFont: { family: 'Outfit', weight: 'bold' },
                        bodyFont: { family: 'Inter' },
                        borderColor: 'rgba(255,255,255,0.06)',
                        borderWidth: 1
                    }
                },
                scales: {
                    x: {
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: '#6b7280',
                            font: { family: 'Inter', size: 9 },
                            maxTicksLimit: 6
                        }
                    },
                    y: {
                        grid: {
                            color: 'rgba(255,255,255,0.03)'
                        },
                        ticks: {
                            color: '#6b7280',
                            font: { family: 'Inter', size: 9 },
                            precision: 0
                        },
                        beginAtZero: true
                    }
                }
            }
        };

        trafficChartInstance = new Chart(ctx, chartConfig);
    }

    // -------------------------------------------------------------
    // 5. REST API CORE DATA FETCHING
    // -------------------------------------------------------------
    
    // A. FETCH REAL-TIME STATS COUNTERS
    async function fetchDashboardStats() {
        try {
            const res = await fetch(`/api/stats?minutes=${statsIntervalMinutes}`);
            if (!res.ok) return;
            const data = await res.json();
            
            // Choose dataset depending on active Tab
            const activeStats = (statsIntervalMinutes === 30) ? data.interval_stats : data.todays_stats;
            
            // Update counter widgets with smooth scaling transitions
            updateCounter("countCarsVal", activeStats.car);
            updateCounter("countMotosVal", activeStats.motorcycle);
            updateCounter("countPersonsVal", activeStats.person);
            
        } catch (err) {
            console.error("Error fetching stats:", err);
        }
    }

    function updateCounter(elementId, newValue) {
        const el = document.getElementById(elementId);
        const currVal = parseInt(el.textContent) || 0;
        
        if (currVal !== newValue) {
            el.textContent = newValue;
            // Add a brief animation trigger
            el.style.transform = "scale(1.15)";
            el.style.transition = "transform 0.15s ease-out";
            setTimeout(() => {
                el.style.transform = "scale(1)";
            }, 150);
        }
    }

    // B. FETCH TIMELINE CHARTS
    async function fetchChartTimeline() {
        try {
            const res = await fetch(`/api/charts?type=${activeChartType}`);
            if (!res.ok) return;
            const data = await res.json();

            // Set chart type dynamically
            trafficChartInstance.config.type = (activeChartType === 'trends') ? 'bar' : 'line';
            
            trafficChartInstance.data.labels = data.labels;
            trafficChartInstance.data.datasets[0].data = data.car;
            trafficChartInstance.data.datasets[1].data = data.motorcycle;
            trafficChartInstance.data.datasets[2].data = data.person;
            
            trafficChartInstance.update('none'); // Update without full layout recalculations to save memory
        } catch (err) {
            console.error("Error updating charts:", err);
        }
    }

    // C. FETCH SYSTEM PERFORMANCE METRICS
    async function fetchPerformanceMetrics() {
        try {
            // Live stats
            const resPerf = await fetch('/api/performance');
            if (resPerf.ok) {
                const perf = await resPerf.ok ? await resPerf.json() : null;
                if (perf) {
                    liveFpsVal.textContent = `${perf.actual_display_fps.toFixed(1)} FPS`;
                    yoloLatencyVal.textContent = `${Math.round(perf.avg_yolo_ms)} ms`;
                    cpuPercentVal.textContent = `${Math.round(perf.cpu_usage)}%`;
                    cpuProgressFill.style.width = `${perf.cpu_usage}%`;
                }
            }
        } catch (err) {
            console.error("Error fetching perf metrics:", err);
        }
    }

    // -------------------------------------------------------------
    // 6. CAMERA STREAM SWITCHING & CRUD MANAGEMENT
    // -------------------------------------------------------------
    async function fetchCamerasList() {
        try {
            const res = await fetch('/api/cameras');
            const cameras = await res.json();
            
            const activeRes = await fetch('/api/cameras/active');
            const activeCam = activeRes.ok ? await activeRes.json() : null;
            
            if (activeCam) {
                activeCameraName.textContent = activeCam.name;
            } else {
                activeCameraName.textContent = "Aucune caméra";
            }

            camerasGridList.innerHTML = "";
            cameras.forEach(cam => {
                const isActive = activeCam && activeCam.id === cam.id;
                
                const card = document.createElement("div");
                card.className = `camera-card ${isActive ? 'active' : ''}`;
                
                card.innerHTML = `
                    <div class="cam-meta">
                        <h4>${cam.name}</h4>
                        <span title="${cam.source}">${cam.source}</span>
                    </div>
                    <div class="cam-actions">
                        <button class="mini-icon-btn switch-cam ${isActive ? 'active-cam' : ''}" data-id="${cam.id}" data-source="${cam.source}" title="Activer cette caméra">
                            <i data-lucide="${isActive ? 'play' : 'video'}"></i>
                        </button>
                        <button class="mini-icon-btn delete" data-id="${cam.id}" title="Supprimer la caméra">
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                `;
                
                camerasGridList.appendChild(card);
            });
            
            // Re-render new lucide icons
            lucide.createIcons();
            
            // Attach actions
            attachCameraActions();
        } catch (err) {
            console.error("Error listing cameras:", err);
        }
    }

    function attachCameraActions() {
        // Toggle Switch active camera
        document.querySelectorAll(".switch-cam").forEach(btn => {
            btn.addEventListener("click", async () => {
                const id = btn.getAttribute("data-id");
                try {
                    // Update streaming UI status
                    activeCameraName.textContent = "Lancement du flux...";
                    videoStreamImage.src = ""; // Reset stream temporarily to prevent frozen frames
                    
                    const res = await fetch('/api/cameras/switch', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id: parseInt(id) })
                    });
                    
                    if (res.ok) {
                        // Reload stream source
                        videoStreamImage.src = "/video_feed?t=" + new Date().getTime();
                        fetchCamerasList();
                        
                        // Flash dashboard counters on switch
                        fetchDashboardStats();
                        fetchChartTimeline();
                    }
                } catch (e) {
                    console.error("Error switching camera stream:", e);
                }
            });
        });

        // Delete camera card
        document.querySelectorAll(".camera-card .delete").forEach(btn => {
            btn.addEventListener("click", async () => {
                const id = btn.getAttribute("data-id");
                if (confirm("Voulez-vous vraiment supprimer cette caméra de votre liste ?")) {
                    try {
                        const res = await fetch(`/api/cameras/${id}`, { method: 'DELETE' });
                        if (res.ok) {
                            fetchCamerasList();
                            // If deleting the active camera, stream automatically switches inside backend
                            videoStreamImage.src = "/video_feed?t=" + new Date().getTime();
                        }
                    } catch (e) {
                        console.error("Error deleting camera:", e);
                    }
                }
            });
        });
    }

    // Modal submit - Add new camera
    addCameraForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name = document.getElementById("cameraInputName").value;
        const source = document.getElementById("cameraInputSource").value;
        
        try {
            const res = await fetch('/api/cameras', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, source })
            });
            
            if (res.ok) {
                closeModal();
                fetchCamerasList();
            } else {
                const err = await res.json();
                alert("Erreur: " + err.error);
            }
        } catch (err) {
            console.error("Error saving camera:", err);
        }
    });

    // -------------------------------------------------------------
    // 7. SETTINGS SYNCHRONISATION (SLIDERS & TOGGLES)
    // -------------------------------------------------------------
    async function loadSettings() {
        try {
            const res = await fetch('/api/settings');
            if (!res.ok) return;
            const cfg = await res.json();
            
            // Set slider values
            sliderCountingLine.value = cfg.counting_line_pos;
            valCountingLine.textContent = `${Math.round(cfg.counting_line_pos * 100)}%`;

            const orientation = cfg.counting_line_orientation || "vertical";
            btnOrientVertical.classList.toggle("active", orientation === "vertical");
            btnOrientHorizontal.classList.toggle("active", orientation === "horizontal");
            
            sliderConfidence.value = cfg.confidence_threshold;
            valConfidence.textContent = `${Math.round(cfg.confidence_threshold * 100)}%`;
            
            sliderAiFps.value = cfg.fps_ai;
            valAiFps.textContent = `${cfg.fps_ai} FPS`;

            sliderDisplayFps.value = cfg.fps_display;
            valDisplayFps.textContent = `${cfg.fps_display} FPS`;
            
            // Set checkboxes
            chkCars.checked = cfg.count_cars;
            chkMotos.checked = cfg.count_motos;
            chkPersons.checked = cfg.count_persons;
            chkOverlays.checked = cfg.show_overlays;
            
        } catch (e) {
            console.error("Error loading settings:", e);
        }
    }

    async function saveSettings() {
        const activeOrient = btnOrientVertical.classList.contains("active") ? "vertical" : "horizontal";
        const payload = {
            counting_line_pos: parseFloat(sliderCountingLine.value),
            counting_line_orientation: activeOrient,
            confidence_threshold: parseFloat(sliderConfidence.value),
            fps_ai: parseInt(sliderAiFps.value),
            fps_display: parseInt(sliderDisplayFps.value),
            count_cars: chkCars.checked,
            count_motos: chkMotos.checked,
            count_persons: chkPersons.checked,
            show_overlays: chkOverlays.checked
        };
        
        try {
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } catch (err) {
            console.error("Error saving configuration:", err);
        }
    }

    // Load current model on startup
    fetch('/api/engine/model').then(r => r.json()).then(data => {
        selectYoloModel.value = data.model;
    });

    // Model selector
    selectYoloModel.addEventListener("change", async () => {
        const model = selectYoloModel.value;
        modelSwitchStatus.textContent = "Chargement du modèle...";
        modelSwitchStatus.style.color = "#f59e0b";
        try {
            await fetch('/api/engine/model', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ model })
            });
            setTimeout(() => {
                videoStreamImage.src = "/video_feed?t=" + new Date().getTime();
                modelSwitchStatus.textContent = "Modèle actif : " + model;
                modelSwitchStatus.style.color = "#00ff87";
            }, 4000);
        } catch (err) {
            modelSwitchStatus.textContent = "Erreur lors du changement.";
            modelSwitchStatus.style.color = "#ef4444";
        }
    });

    // Restart engine button
    btnRestartEngine.addEventListener("click", async () => {
        btnRestartEngine.classList.add("spinning");
        btnRestartEngine.disabled = true;
        try {
            await fetch('/api/engine/restart', { method: 'POST' });
            // Reload video stream
            setTimeout(() => {
                videoStreamImage.src = "/video_feed?t=" + new Date().getTime();
            }, 1500);
        } catch (err) {
            console.error("Error restarting engine:", err);
        } finally {
            setTimeout(() => {
                btnRestartEngine.classList.remove("spinning");
                btnRestartEngine.disabled = false;
            }, 2000);
        }
    });

    // Clear stats button
    btnClearStats.addEventListener("click", async () => {
        if (!confirm("Effacer toutes les données de comptage ? Cette action est irréversible.")) return;
        try {
            await fetch('/api/stats/clear', { method: 'POST' });
            fetchDashboardStats();
            fetchChartTimeline();
            fetchCustomReport();
        } catch (err) {
            console.error("Error clearing stats:", err);
        }
    });

    // Orientation toggle buttons
    [btnOrientVertical, btnOrientHorizontal].forEach(btn => {
        btn.addEventListener("click", () => {
            btnOrientVertical.classList.remove("active");
            btnOrientHorizontal.classList.remove("active");
            btn.classList.add("active");
            saveSettings();
        });
    });

    // Attach listeners to sliders for rapid visual feedback
    sliderCountingLine.addEventListener("input", (e) => {
        valCountingLine.textContent = `${Math.round(e.target.value * 100)}%`;
        saveSettings();
    });
    
    sliderConfidence.addEventListener("input", (e) => {
        valConfidence.textContent = `${Math.round(e.target.value * 100)}%`;
        saveSettings();
    });
    
    sliderAiFps.addEventListener("input", (e) => {
        valAiFps.textContent = `${e.target.value} FPS`;
        saveSettings();
    });

    sliderDisplayFps.addEventListener("input", (e) => {
        valDisplayFps.textContent = `${e.target.value} FPS`;
        saveSettings();
    });

    // Attach checkbox changes
    [chkCars, chkMotos, chkPersons, chkOverlays].forEach(chk => {
        chk.addEventListener("change", saveSettings);
    });

    // -------------------------------------------------------------
    // 8. ARCHIVE REPORTS & EXPORTS LOGIC
    // -------------------------------------------------------------
    
    // Set default dates: Start is today at 00:00, End is now
    function setDefaultReportDates() {
        const now = new Date();
        
        // Local offset correction for datetime-local input fields
        const tzOffset = now.getTimezoneOffset() * 60000;
        
        // Start date: Today midnight
        const midnight = new Date(now);
        midnight.setHours(0, 0, 0, 0);
        
        const localMidnightIso = new Date(midnight - tzOffset).toISOString().slice(0, 16);
        const localNowIso = new Date(now - tzOffset).toISOString().slice(0, 16);
        
        reportStartDate.value = localMidnightIso;
        reportEndDate.value = localNowIso;
    }
    
    async function fetchCustomReport() {
        const start = reportStartDate.value.replace("T", " ") + ":00";
        const end = reportEndDate.value.replace("T", " ") + ":00";
        
        try {
            const res = await fetch(`/api/reports?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`);
            if (!res.ok) return;
            const data = await res.json();
            
            // Set values
            repCarSum.textContent = data.summary.car;
            repMotoSum.textContent = data.summary.motorcycle;
            repPersonSum.textContent = data.summary.person;
            
        } catch (e) {
            console.error("Error loading reports summary:", e);
        }
    }
    
    btnGenerateReport.addEventListener("click", fetchCustomReport);
    
    btnExportCSV.addEventListener("click", () => {
        const start = reportStartDate.value.replace("T", " ") + ":00";
        const end = reportEndDate.value.replace("T", " ") + ":00";
        
        // Trigger browser direct attachment download by shifting window location
        window.location.href = `/api/reports/export?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`;
    });

    // -------------------------------------------------------------
    // 9. APP INITIALISATION & POLLING LOOP
    // -------------------------------------------------------------
    function initializeApp() {
        setupChart();
        loadSettings();
        fetchCamerasList();
        setDefaultReportDates();
        fetchCustomReport();
        
        // Run initial data load
        fetchDashboardStats();
        fetchChartTimeline();
        fetchPerformanceMetrics();
        
        // Set intervals for UI updates
        pollIntervalId = setInterval(() => {
            fetchDashboardStats();
            fetchPerformanceMetrics();
        }, 2000);

        // Chart polling interval (update charts every 5 seconds)
        chartPollIntervalId = setInterval(() => {
            fetchChartTimeline();
        }, 5000);
    }

    initializeApp();
});
