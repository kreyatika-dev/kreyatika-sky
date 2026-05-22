import sqlite3
import os
from datetime import datetime, timedelta

class AnalyticsDatabase:
    def __init__(self, db_path="analytics.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. Table for Camera configurations
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS cameras (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    active INTEGER DEFAULT 0
                )
            ''')
            
            # 2. Table for Detections (strictly structured, NO image paths)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    direction TEXT NOT NULL
                )
            ''')
            
            conn.commit()
            
        # Seed default camera if none exist
        self._seed_default_camera()

    def _seed_default_camera(self):
        cameras = self.list_cameras()
        if not cameras:
            self.add_camera("Vidéo de Démo (Comptage)", "sample.mp4", active=True)
            self.add_camera("Webcam Locale (USB)", "0", active=False)
            self.add_camera("Flux Simulation (RTSP)", "rtsp://127.0.0.1:8554/live", active=False)

    # --- Detection Logging & Querying ---
    
    def clear_detections(self):
        with self._get_connection() as conn:
            conn.cursor().execute('DELETE FROM detections')
            conn.commit()

    def log_detection(self, class_name, direction):
        """Logs a counting event (car, motorcycle, person) with local timestamp."""
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO detections (timestamp, class_name, direction)
                VALUES (?, ?, ?)
            ''', (now_str, class_name, direction))
            conn.commit()

    def get_stats_for_interval(self, minutes=30):
        """Returns total counts per class in the last N minutes."""
        since_time = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
        stats = {"car": 0, "motorcycle": 0, "person": 0}
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT class_name, COUNT(*) 
                FROM detections 
                WHERE timestamp >= ? 
                GROUP BY class_name
            ''', (since_time,))
            
            for row in cursor.fetchall():
                cls, count = row
                if cls in stats:
                    stats[cls] = count
        return stats

    def get_todays_stats(self):
        """Returns counts for today (since midnight)."""
        today_start = datetime.now().strftime('%Y-%m-%d 00:00:00')
        stats = {"car": 0, "motorcycle": 0, "person": 0}
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT class_name, COUNT(*) 
                FROM detections 
                WHERE timestamp >= ? 
                GROUP BY class_name
            ''', (today_start,))
            
            for row in cursor.fetchall():
                cls, count = row
                if cls in stats:
                    stats[cls] = count
        return stats

    def get_recent_counts_grouped_by_minute(self, minutes=30):
        """
        Groups detections in the last N minutes by 1-minute intervals.
        Used to draw real-time active timelines in Chart.js.
        """
        since_time = (datetime.now() - timedelta(minutes=minutes)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Pre-fill all minutes to ensure the chart is continuous and pretty
        timeline = {}
        for i in range(minutes, -1, -1):
            minute_str = (datetime.now() - timedelta(minutes=i)).strftime('%H:%M')
            timeline[minute_str] = {"car": 0, "motorcycle": 0, "person": 0}
            
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT strftime('%H:%M', timestamp) as minute_label, class_name, COUNT(*)
                FROM detections
                WHERE timestamp >= ?
                GROUP BY minute_label, class_name
            ''', (since_time,))
            
            for row in cursor.fetchall():
                minute_label, cls, count = row
                if minute_label in timeline and cls in timeline[minute_label]:
                    timeline[minute_label][cls] = count
                    
        # Format for Chart.js
        labels = sorted(list(timeline.keys()))
        car_data = [timeline[lbl]["car"] for lbl in labels]
        moto_data = [timeline[lbl]["motorcycle"] for lbl in labels]
        person_data = [timeline[lbl]["person"] for lbl in labels]
        
        return {
            "labels": labels,
            "car": car_data,
            "motorcycle": moto_data,
            "person": person_data
        }

    def get_hourly_trends_24h(self):
        """
        Groups detections in the last 24 hours by hourly intervals.
        """
        since_time = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Pre-fill hours
        timeline = {}
        for i in range(24, -1, -1):
            hour_str = (datetime.now() - timedelta(hours=i)).strftime('%H:00')
            timeline[hour_str] = {"car": 0, "motorcycle": 0, "person": 0}
            
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT strftime('%H:00', timestamp) as hour_label, class_name, COUNT(*)
                FROM detections
                WHERE timestamp >= ?
                GROUP BY hour_label, class_name
            ''', (since_time,))
            
            for row in cursor.fetchall():
                hour_label, cls, count = row
                if hour_label in timeline and cls in timeline[hour_label]:
                    timeline[hour_label][cls] = count
                    
        labels = sorted(list(timeline.keys()))
        return {
            "labels": labels,
            "car": [timeline[lbl]["car"] for lbl in labels],
            "motorcycle": [timeline[lbl]["motorcycle"] for lbl in labels],
            "person": [timeline[lbl]["person"] for lbl in labels]
        }

    def get_custom_report_data(self, start_date, end_date):
        """Returns aggregated summary and all detection logs within date range."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Totals
            cursor.execute('''
                SELECT class_name, COUNT(*) as cnt
                FROM detections
                WHERE timestamp >= ? AND timestamp <= ?
                GROUP BY class_name
            ''', (start_date, end_date))
            
            summary = {"car": 0, "motorcycle": 0, "person": 0}
            for row in cursor.fetchall():
                cls = row["class_name"]
                if cls in summary:
                    summary[cls] = row["cnt"]
                    
            # Logs
            cursor.execute('''
                SELECT timestamp, class_name, direction
                FROM detections
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT 1000
            ''', (start_date, end_date))
            
            logs = [{"timestamp": r["timestamp"], "class_name": r["class_name"], "direction": r["direction"]} for r in cursor.fetchall()]
            
            return {
                "summary": summary,
                "logs": logs
            }

    # --- Camera Settings ---
    
    def list_cameras(self):
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, source, active FROM cameras')
            return [dict(row) for row in cursor.fetchall()]

    def add_camera(self, name, source, active=False):
        is_active = 1 if active else 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # If adding as active, deactivate others
            if is_active:
                cursor.execute('UPDATE cameras SET active = 0')
                
            cursor.execute('''
                INSERT INTO cameras (name, source, active)
                VALUES (?, ?, ?)
            ''', (name, source, is_active))
            conn.commit()
            return cursor.lastrowid

    def delete_camera(self, camera_id):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if we're deleting the active camera
            cursor.execute('SELECT active FROM cameras WHERE id = ?', (camera_id,))
            row = cursor.fetchone()
            was_active = row and row[0] == 1
            
            cursor.execute('DELETE FROM cameras WHERE id = ?', (camera_id,))
            
            # If we deleted the active camera, set another one as active
            if was_active:
                cursor.execute('SELECT id FROM cameras LIMIT 1')
                next_row = cursor.fetchone()
                if next_row:
                    cursor.execute('UPDATE cameras SET active = 1 WHERE id = ?', (next_row[0],))
            conn.commit()

    def set_active_camera(self, camera_id):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE cameras SET active = 0')
            cursor.execute('UPDATE cameras SET active = 1 WHERE id = ?', (camera_id,))
            conn.commit()

    def get_active_camera(self):
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT id, name, source, active FROM cameras WHERE active = 1 LIMIT 1')
            row = cursor.fetchone()
            if row:
                return dict(row)
            # Fallback if no active is found (take first)
            cursor.execute('SELECT id, name, source, active FROM cameras LIMIT 1')
            row = cursor.fetchone()
            return dict(row) if row else None
