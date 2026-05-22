import time
import os
import platform
import socket
import psutil
from datetime import datetime, timedelta
from flask import Flask, Response, jsonify, render_template, request, make_response
import io
import csv

from database import AnalyticsDatabase
from detector import YOLODetector

app = Flask(__name__, template_folder='templates', static_folder='static')

# Initialize DB and AI Engine
DB_PATH = os.environ.get("DB_PATH", "analytics.db")
db = AnalyticsDatabase(DB_PATH)
detector = YOLODetector(database_path=DB_PATH, model_path="yolo11s.pt")

# Boot AI Engine with the active camera from database
active_cam = db.get_active_camera()
if active_cam:
    print(f"Booting AI engine with active camera: {active_cam['name']} ({active_cam['source']})")
    detector.start(active_cam['source'])
else:
    print("Warning: No active camera configured. AI Engine is idle.")

# --- Web UI Routes ---

@app.route('/')
def dashboard():
    return render_template('index.html')

# --- Live Streaming Route ---

@app.route('/video_feed')
def video_feed():
    def generate():
        while True:
            frame_bytes = detector.get_video_frame()
            if frame_bytes is None:
                time.sleep(0.05)
                continue
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            
            # Throttle stream matching display FPS
            time.sleep(1.0 / max(1, detector.get_config()["fps_display"]))
            
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

# --- REST API Endpoints ---

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Retrieve interval stats (default 30m) and daily totals."""
    minutes = request.args.get('minutes', 30, type=int)
    
    interval_stats = db.get_stats_for_interval(minutes)
    todays_stats = db.get_todays_stats()
    
    return jsonify({
        "interval_minutes": minutes,
        "interval_stats": interval_stats,
        "todays_stats": todays_stats
    })

@app.route('/api/charts', methods=['GET'])
def get_chart_data():
    """Retrieve timeline datasets for Chart.js. Supports 'realtime' (30m) or 'trends' (24h)."""
    chart_type = request.args.get('type', 'realtime')
    
    if chart_type == 'trends':
        data = db.get_hourly_trends_24h()
    else:
        # Default: 30 minutes timeline
        data = db.get_recent_counts_grouped_by_minute(30)
        
    return jsonify(data)

@app.route('/api/settings', methods=['GET', 'POST'])
def manage_settings():
    """Fetch or update AI Detector settings."""
    if request.method == 'POST':
        new_settings = request.json
        detector.update_config(new_settings)
        return jsonify({"status": "success", "config": detector.get_config()})
    
    return jsonify(detector.get_config())

@app.route('/api/performance', methods=['GET'])
def get_performance():
    """Fetch live FPS, latency, CPU, and memory stats."""
    metrics = detector.get_perf_metrics()
    return jsonify(metrics)

@app.route('/api/system-info', methods=['GET'])
def system_info():
    """Machine specs and optimized recommendation for FPS."""
    mem = psutil.virtual_memory()
    cpu_usage = psutil.cpu_percent()
    cores = psutil.cpu_count(logical=True)
    
    # Suggest AI processing speed
    suggest_ai = 8
    if cores <= 2:
        suggest_ai = 4
    elif cores >= 8:
        suggest_ai = 12
        
    reason = f"Actuellement sur {cores} coeurs logiques avec {cpu_usage}% d'usage CPU."
    if cpu_usage > 65:
        suggest_ai = max(2, suggest_ai - 3)
        reason += " CPU élevé, réduction recommandée de la cadence d'analyse."

    return jsonify({
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "machine": platform.machine(),
        "cpu_cores": cores,
        "cpu_usage_percent": cpu_usage,
        "ram_usage_percent": mem.percent,
        "ram_total_gb": round(mem.total / (1024**3), 1),
        "suggestion": {
            "fps_display": 15 if cpu_usage > 75 else 20,
            "fps_ai": suggest_ai,
            "reason": reason
        }
    })

# --- Camera Management API ---

@app.route('/api/cameras', methods=['GET', 'POST'])
def handle_cameras():
    """List or add cameras."""
    if request.method == 'POST':
        data = request.json
        name = data.get('name', 'Nouvelle Caméra').strip()
        source = data.get('source', '').strip()
        
        if not source:
            return jsonify({"error": "L'adresse IP ou l'index de flux est requis"}), 400
            
        # Format bare IP strings to standard RTSP URLs
        if source and not source.startswith(('rtsp://', 'rtmp://', 'http://', 'https://')) and '.' in source:
            source = f"rtsp://admin:admin@{source}:554/live/ch0"
            
        cam_id = db.add_camera(name, source, active=False)
        return jsonify({"status": "success", "id": cam_id, "camera": {"id": cam_id, "name": name, "source": source, "active": 0}}), 201
        
    return jsonify(db.list_cameras())

@app.route('/api/cameras/active', methods=['GET'])
def get_active_camera():
    """Fetch details of the currently selected active camera."""
    cam = db.get_active_camera()
    if cam:
        return jsonify(cam)
    return jsonify({"error": "Aucune caméra active"}), 404

@app.route('/api/cameras/switch', methods=['POST'])
def switch_camera():
    """Dynamically switch the running AI detector to another camera stream."""
    data = request.json
    cam_id = data.get('id')
    
    if not cam_id:
        return jsonify({"error": "ID de la caméra requis"}), 400
        
    # Set active in database
    db.set_active_camera(cam_id)
    active_cam_details = db.get_active_camera()
    
    if active_cam_details:
        print(f"Switching AI Stream to: {active_cam_details['name']} ({active_cam_details['source']})")
        # Hot reload background thread
        detector.start(active_cam_details['source'])
        return jsonify({"status": "switched", "camera": active_cam_details})
    
    return jsonify({"error": "Caméra introuvable"}), 404

@app.route('/api/cameras/<int:camera_id>', methods=['DELETE'])
def delete_camera(camera_id):
    """Deletes a configured camera from the SQLite storage."""
    db.delete_camera(camera_id)
    
    # Check if the currently running detector's camera was changed/affected
    curr_active = db.get_active_camera()
    if curr_active:
        # Check config settings and restart detector if different
        detector.start(curr_active['source'])
        
    return jsonify({"status": "deleted"})

# --- Reports & Exports API ---

@app.route('/api/engine/restart', methods=['POST'])
def restart_engine():
    active_cam_details = db.get_active_camera()
    if active_cam_details:
        print(f"Restarting AI engine on: {active_cam_details['name']}")
        detector.start(active_cam_details['source'])
        return jsonify({"status": "restarted", "camera": active_cam_details['name']})
    return jsonify({"error": "Aucune caméra active"}), 404

@app.route('/api/stats/clear', methods=['POST'])
def clear_stats():
    db.clear_detections()
    return jsonify({"status": "cleared"})

@app.route('/api/reports', methods=['GET'])
def get_reports():
    """Get summarized events and detailed logs for custom date ranges."""
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    
    if not start_str or not end_str:
        # Default: last 24 hours
        start_str = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        end_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
    report = db.get_custom_report_data(start_str, end_str)
    return jsonify(report)

@app.route('/api/reports/export', methods=['GET'])
def export_reports():
    """Export custom range logs to a clean downloadable CSV file."""
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    
    if not start_str or not end_str:
        start_str = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d 00:00:00')
        end_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
    report_data = db.get_custom_report_data(start_str, end_str)
    logs = report_data.get('logs', [])
    
    # Generate CSV in memory
    dest = io.StringIO()
    writer = csv.writer(dest)
    writer.writerow(["Horodatage (Timestamp)", "Type de Cible (Class Name)", "Sens (Direction)"])
    
    for row in logs:
        writer.writerow([row["timestamp"], row["class_name"].upper(), row["direction"].upper()])
        
    response = make_response(dest.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename=kreyatika_sky_export_{datetime.now().strftime('%Y%m%d%H%M')}.csv"
    response.headers["Content-type"] = "text/csv"
    return response

if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True, use_reloader=False)
    finally:
        print("Shutting down AI engine thread...")
        detector.stop()

import atexit
atexit.register(detector.stop)
