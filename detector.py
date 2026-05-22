import cv2
import time
import os
import threading
import numpy as np
import psutil
from ultralytics import YOLO
from database import AnalyticsDatabase

# --- Helper: Overlapping Box Filter (NMS / Containment) ---
def filter_overlapping_boxes(boxes, classes, confidences, iou_threshold=0.40, containment_threshold=0.70):
    """
    Applies Non-Maximum Suppression (NMS) and containment checks
    to prevent double counting of overlapping bounding boxes (e.g. ghost boxes).
    """
    if len(boxes) == 0:
        return []
        
    keep_indices = []
    idxs = np.argsort(confidences)[::-1]
    
    while len(idxs) > 0:
        last = len(idxs) - 1
        i = idxs[0]
        keep_indices.append(i)
        
        suppress = [0]
        for pos in range(1, len(idxs)):
            j = idxs[pos]
            
            # Only compare if they are of the same object class category
            if classes[i] != classes[j]:
                continue
                
            # Intersection box
            xx1 = max(boxes[i][0], boxes[j][0])
            yy1 = max(boxes[i][1], boxes[j][1])
            xx2 = min(boxes[i][2], boxes[j][2])
            yy2 = min(boxes[i][3], boxes[j][3])
            
            w = max(0, xx2 - xx1 + 1)
            h = max(0, yy2 - yy1 + 1)
            
            overlap_area = w * h
            area_i = (boxes[i][2] - boxes[i][0] + 1) * (boxes[i][3] - boxes[i][1] + 1)
            area_j = (boxes[j][2] - boxes[j][0] + 1) * (boxes[j][3] - boxes[j][1] + 1)
            
            # Intersection over Union (IoU)
            iou = overlap_area / float(area_i + area_j - overlap_area)
            
            # Containment Check (one box mostly inside another)
            min_area = min(area_i, area_j)
            containment = overlap_area / float(min_area)
            
            if iou > iou_threshold or containment > containment_threshold:
                suppress.append(pos)
                
        idxs = np.delete(idxs, suppress)
        
    return keep_indices


# --- Helper: Stable Fallback Geometric Tracker ---
class BBoxTracker:
    def __init__(self, max_disappeared=15):
        self.next_object_id = 10000  # Start fallback IDs at 10000 to avoid collision with YOLO tracking IDs
        self.objects = {}            # {id: [x1, y1, x2, y2]}
        self.categories = {}         # {id: category}
        self.disappeared = {}        # {id: count}
        self.max_disappeared = max_disappeared

    def register(self, bbox, category):
        self.objects[self.next_object_id] = bbox
        self.categories[self.next_object_id] = category
        self.disappeared[self.next_object_id] = 0
        obj_id = self.next_object_id
        self.next_object_id += 1
        return obj_id

    def deregister(self, obj_id):
        self.objects.pop(obj_id, None)
        self.categories.pop(obj_id, None)
        self.disappeared.pop(obj_id, None)

    def update(self, rects, categories):
        # rects: list of [x1, y1, x2, y2]
        if len(rects) == 0:
            for obj_id in list(self.disappeared.keys()):
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self.deregister(obj_id)
            return {}

        input_centroids = np.zeros((len(rects), 2), dtype="int")
        for i, (x1, y1, x2, y2) in enumerate(rects):
            cX = int((x1 + x2) / 2.0)
            cY = int((y1 + y2) / 2.0)
            input_centroids[i] = (cX, cY)

        if len(self.objects) == 0:
            assigned_ids = []
            for i in range(len(rects)):
                assigned_ids.append(self.register(rects[i], categories[i]))
            return {assigned_ids[i]: (rects[i], categories[i]) for i in range(len(rects))}
        else:
            object_ids = list(self.objects.keys())
            object_centroids = []
            for bbox in self.objects.values():
                cX = int((bbox[0] + bbox[2]) / 2.0)
                cY = int((bbox[1] + bbox[3]) / 2.0)
                object_centroids.append((cX, cY))

            D = np.linalg.norm(np.array(object_centroids)[:, np.newaxis] - input_centroids, axis=2)

            rows = D.min(axis=1).argsort()
            cols = D.argmin(axis=1)[rows]

            used_rows = set()
            used_cols = set()

            assigned = {}

            for (row, col) in zip(rows, cols):
                if row in used_rows or col in used_cols:
                    continue

                if D[row, col] > 150:  # Max distance in pixels
                    continue

                obj_id = object_ids[row]
                self.objects[obj_id] = rects[col]
                self.categories[obj_id] = categories[col]
                self.disappeared[obj_id] = 0

                used_rows.add(row)
                used_cols.add(col)
                assigned[obj_id] = (rects[col], categories[col])

            unused_rows = set(range(0, D.shape[0])).difference(used_rows)
            unused_cols = set(range(0, D.shape[1])).difference(used_cols)

            for row in unused_rows:
                obj_id = object_ids[row]
                self.disappeared[obj_id] += 1
                if self.disappeared[obj_id] > self.max_disappeared:
                    self.deregister(obj_id)

            for col in unused_cols:
                new_id = self.register(rects[col], categories[col])
                assigned[new_id] = (rects[col], categories[col])

            return assigned


# --- Core YOLODetector ---
class YOLODetector:
    def __init__(self, database_path="analytics.db", model_path="yolo11n.pt"):
        self.db = AnalyticsDatabase(database_path)
        
        # Load YOLO Model
        print(f"Loading YOLO model from {model_path}...")
        self.model = YOLO(model_path)
        
        # Runtime variables
        self.output_frame = None
        self.lock = threading.Lock()
        self.stop_worker = False
        self.worker_thread = None
        
        # System settings / Configuration (adjustable on the fly)
        self.config = {
            "count_cars": True,
            "count_motos": True,
            "count_persons": True,
            "show_overlays": True,
            "fps_display": 20,
            "fps_ai": 10,
            "counting_line_pos": 0.5,
            "counting_line_orientation": "vertical",
            "confidence_threshold": 0.45
        }
        
        # Performance Tracking
        self.perf_metrics = {
            "actual_display_fps": 0,
            "actual_ai_fps": 0,
            "avg_yolo_ms": 0.0,
            "cpu_usage": 0,
            "frame_count_display": 0,
            "frame_count_ai": 0,
            "last_fps_reset": time.time()
        }
        
        # Define tracking dictionaries
        self.track_history = {}   # {id: last_position (x or y)}
        self.track_starts = {}    # {id: stable_frame_count}
        self.track_cooldown = {}  # {id: last_counted_timestamp}
        self.bbox_tracker = BBoxTracker(max_disappeared=15)

    def update_config(self, new_config):
        with self.lock:
            for key, val in new_config.items():
                if key in self.config:
                    if key in ["fps_display", "fps_ai"]:
                        self.config[key] = int(val)
                    elif key in ["counting_line_pos", "confidence_threshold"]:
                        self.config[key] = float(val)
                    elif key == "counting_line_orientation":
                        self.config[key] = str(val)
                    else:
                        self.config[key] = bool(val)
            print(f"Config updated: {self.config}")

    def get_config(self):
        with self.lock:
            return self.config.copy()

    def get_perf_metrics(self):
        # Calculate actual FPS on request
        now = time.time()
        with self.lock:
            dt = now - self.perf_metrics["last_fps_reset"]
            if dt >= 2.0:
                self.perf_metrics["actual_display_fps"] = round(self.perf_metrics["frame_count_display"] / dt, 1)
                self.perf_metrics["actual_ai_fps"] = round(self.perf_metrics["frame_count_ai"] / dt, 1)
                self.perf_metrics["frame_count_display"] = 0
                self.perf_metrics["frame_count_ai"] = 0
                self.perf_metrics["last_fps_reset"] = now
                self.perf_metrics["cpu_usage"] = psutil.cpu_percent()
            
            return {
                "actual_display_fps": self.perf_metrics["actual_display_fps"],
                "actual_ai_fps": self.perf_metrics["actual_ai_fps"],
                "avg_yolo_ms": round(self.perf_metrics["avg_yolo_ms"], 1),
                "fps_display_target": self.config["fps_display"],
                "fps_ai_target": self.config["fps_ai"],
                "cpu_usage": self.perf_metrics["cpu_usage"]
            }

    def start(self, camera_source):
        self.stop()
        self.stop_worker = False
        self.track_history.clear()
        self.track_starts.clear()
        self.track_cooldown.clear()
        self.bbox_tracker = BBoxTracker(max_disappeared=15)
        
        self.worker_thread = threading.Thread(target=self._ai_worker, args=(camera_source,))
        self.worker_thread.daemon = True
        self.worker_thread.start()

    def stop(self):
        self.stop_worker = True
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=3.0)

    def get_video_frame(self):
        with self.lock:
            if self.output_frame is None:
                return None
            
            self.perf_metrics["frame_count_display"] += 1
            # Encode frame to JPEG
            ret, jpeg = cv2.imencode('.jpg', self.output_frame)
            return jpeg.tobytes() if ret else None

    def _ai_worker(self, camera_source):
        print(f"Opening camera source: {camera_source}...")
        
        # Format source
        source = camera_source
        try:
            source = int(camera_source)
        except (ValueError, TypeError):
            pass
            
        # Open video capture stream
        if isinstance(source, int):
            cap = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
        else:
            cap = cv2.VideoCapture(source)
            
        if not cap.isOpened():
            print(f"Error: Could not open camera source: {camera_source}")
            # Put error slide in frame
            error_img = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(error_img, "ERREUR FLUX VIDEO", (150, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            cv2.putText(error_img, "Impossible d'ouvrir la camera", (140, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            with self.lock:
                self.output_frame = error_img
            return

        # Check if the source is a local video file
        is_file = False
        if isinstance(source, str) and (os.path.exists(source) or os.path.exists(os.path.join(os.getcwd(), source))):
            is_file = True
        
        # Get total frames and actual video FPS if it is a local video file
        video_fps = 30.0
        if is_file:
            fps_prop = cap.get(cv2.CAP_PROP_FPS)
            if fps_prop > 0:
                video_fps = fps_prop
            print(f"Detected local video file. Playback FPS set to: {video_fps}")
        else:
            print(f"AI Counting Engine Active for source: {camera_source}")

        last_processed_time = 0.0
        
        while not self.stop_worker:
            current_time = time.time()
            ret, frame = cap.read()
            if not ret:
                if is_file:
                    print("End of video file reached. Looping cleanly...")
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                    if not ret:
                        # Fallback: close and reopen
                        cap.release()
                        cap = cv2.VideoCapture(source)
                        continue
                else:
                    print("Camera feed lost, attempting to reconnect...")
                    time.sleep(2.0)
                    # Attempt to reopen
                    cap.release()
                    if isinstance(source, int):
                        cap = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION)
                    else:
                        cap = cv2.VideoCapture(source)
                    continue

            # Target AI processing speed (FPS limiting)
            with self.lock:
                fps_ai = self.config["fps_ai"]
                show_overlays = self.config["show_overlays"]
                line_pos = self.config["counting_line_pos"]
                line_orientation = self.config["counting_line_orientation"]
                conf_thresh = self.config["confidence_threshold"]
                count_cars = self.config["count_cars"]
                count_motos = self.config["count_motos"]
                count_persons = self.config["count_persons"]

            # Deciding whether to run AI
            run_ai = True
            if not is_file:
                # Limit AI FPS only for live cameras to optimize CPU performance
                if current_time - last_processed_time < (1.0 / fps_ai):
                    run_ai = False

            if not run_ai:
                # Update visual display frame quickly for smooth rendering on live feeds
                if show_overlays:
                    with self.lock:
                        h, w = frame.shape[:2]
                        draw_frame = frame.copy()
                        if line_orientation == "vertical":
                            lx = int(w * line_pos)
                            cv2.line(draw_frame, (lx, 0), (lx, h), (0, 165, 255), 2)
                            cv2.putText(draw_frame, "LIGNE", (lx + 6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1, cv2.LINE_AA)
                        else:
                            ly = int(h * line_pos)
                            cv2.line(draw_frame, (0, ly), (w, ly), (0, 165, 255), 2)
                            cv2.putText(draw_frame, "LIGNE DE COMPTAGE", (15, ly - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1, cv2.LINE_AA)
                        self.output_frame = draw_frame
                else:
                    with self.lock:
                        self.output_frame = frame.copy()
                continue
                
            last_processed_time = current_time
            with self.lock:
                self.perf_metrics["frame_count_ai"] += 1
                
            height, width = frame.shape[:2]
            line_x = int(width * line_pos)
            line_y = int(height * line_pos)

            # Process YOLO Tracking
            t_start = time.time()
            results = self.model.track(
                frame, 
                persist=True, 
                verbose=False, 
                conf=conf_thresh, 
                tracker="botsort.yaml"
            )
            yolo_dt = (time.time() - t_start) * 1000.0
            
            with self.lock:
                self.perf_metrics["avg_yolo_ms"] = (self.perf_metrics["avg_yolo_ms"] * 0.9) + (yolo_dt * 0.1)

            draw_frame = frame.copy()
            
            # Draw visual guides
            if show_overlays:
                if line_orientation == "vertical":
                    cv2.line(draw_frame, (line_x, 0), (line_x, height), (147, 20, 255), 3)
                    cv2.putText(draw_frame, "LIGNE DE COMPTAGE", (line_x + 8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (147, 20, 255), 2, cv2.LINE_AA)
                else:
                    cv2.line(draw_frame, (0, line_y), (width, line_y), (147, 20, 255), 3)
                    cv2.putText(draw_frame, "LIGNE DE COMPTAGE", (15, line_y - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (147, 20, 255), 2, cv2.LINE_AA)

            # Extract raw predictions to map fallback IDs and filter double counts
            detected_boxes = []
            detected_classes = []
            detected_confidences = []
            yolo_ids = []

            if results and results[0].boxes:
                boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
                classes = results[0].boxes.cls.cpu().numpy().astype(int)
                confidences = results[0].boxes.conf.cpu().numpy()
                
                # Fetch tracking IDs assigned by YOLO model
                y_ids = None
                if results[0].boxes.id is not None:
                    y_ids = results[0].boxes.id.cpu().numpy().astype(int)

                for idx, (box, cls, conf) in enumerate(zip(boxes, classes, confidences)):
                    # Category mappings (including bicycle (class 1) as motorcycle)
                    is_person = (cls in [0, 1])       # person, bicycle
                    is_car = (cls in [2, 5, 7])       # car, bus, truck
                    is_moto = (cls == 3)              # motorcycle

                    if is_person and not count_persons: continue
                    if is_car and not count_cars: continue
                    if is_moto and not count_motos: continue

                    category = None
                    if is_person: category = "person"
                    elif is_car: category = "car"
                    elif is_moto: category = "motorcycle"

                    if category:
                        detected_boxes.append(box.tolist())
                        detected_classes.append(cls)
                        detected_confidences.append(conf)
                        
                        y_id = None
                        if y_ids is not None and idx < len(y_ids):
                            y_id = int(y_ids[idx])
                        yolo_ids.append(y_id)

            # 1. Apply Overlapping Box Filter (NMS) to eliminate double counts of the same object
            keep_indices = filter_overlapping_boxes(detected_boxes, detected_classes, detected_confidences,
                                                     iou_threshold=0.30, containment_threshold=0.60)

            filtered_boxes = [detected_boxes[i] for i in keep_indices]
            filtered_classes = [detected_classes[i] for i in keep_indices]
            filtered_confidences = [detected_confidences[i] for i in keep_indices]
            filtered_yolo_ids = [yolo_ids[i] for i in keep_indices]

            # 2. Update fallback tracker for any bounding boxes that do not have active YOLO tracking IDs
            boxes_without_id = [box for box, y_id in zip(filtered_boxes, filtered_yolo_ids) if y_id is None]
            cats_without_id = []
            for cls in [filtered_classes[i] for i, y_id in enumerate(filtered_yolo_ids) if y_id is None]:
                if cls in [0, 1]: cats_without_id.append("person")
                elif cls in [2, 5, 7]: cats_without_id.append("car")
                else: cats_without_id.append("motorcycle")

            fallback_matches = self.bbox_tracker.update(boxes_without_id, cats_without_id)

            # 3. Process each final object with either its YOLO ID or its fallback ID
            for box, cls, conf, y_id in zip(filtered_boxes, filtered_classes, filtered_confidences, filtered_yolo_ids):
                # Class mapping
                category = "person" if cls in [0, 1] else ("car" if cls in [2, 5, 7] else "motorcycle")
                
                # Resolve final stable ID
                obj_id = y_id
                if obj_id is None:
                    # Find which fallback ID corresponds to this bounding box
                    for fb_id, (fb_box, fb_cat) in fallback_matches.items():
                        if np.array_equal(fb_box, box):
                            obj_id = fb_id
                            break
                    if obj_id is None:
                        obj_id = self.bbox_tracker.register(box, category)

                x1, y1, x2, y2 = box
                center_x = int((x1 + x2) / 2)
                center_y = int((y1 + y2) / 2)

                # Resolve current position and line coord based on orientation
                curr_pos = center_x if line_orientation == "vertical" else center_y
                line_coord = line_x if line_orientation == "vertical" else line_y

                # Increment stable frame count
                self.track_starts[obj_id] = self.track_starts.get(obj_id, 0) + 1

                # True line-crossing detection (change 3: requires 3 stable frames; change 6: crossing logic)
                if obj_id in self.track_history and self.track_starts[obj_id] >= 3:
                    prev_pos = self.track_history[obj_id]
                    prev_side = prev_pos < line_coord
                    curr_side = curr_pos < line_coord

                    if prev_side != curr_side:
                        cooldown_ok = (time.time() - self.track_cooldown.get(obj_id, 0)) > 2.0
                        if cooldown_ok:
                            direction = "out" if curr_pos > prev_pos else "in"
                            print(f"[AI] Line crossed: {category} #{obj_id} → {direction}")
                            self.db.log_detection(category, direction)
                            self.track_cooldown[obj_id] = time.time()

                # Update position history
                self.track_history[obj_id] = curr_pos

                # Draw Visual Overlay Bounding Box
                if show_overlays:
                    if category == "car": color = (255, 191, 0)
                    elif category == "motorcycle": color = (186, 85, 211)
                    else: color = (50, 205, 50)

                    cv2.rectangle(draw_frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(draw_frame, f"{category.upper()} #{obj_id}", (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

            # Clean tracking memory periodically to avoid bloating
            if len(self.track_history) > 1000:
                keys_to_remove = list(self.track_history.keys())[:-200]
                for k in keys_to_remove:
                    self.track_history.pop(k, None)
                    self.track_starts.pop(k, None)
                    self.track_cooldown.pop(k, None)

            with self.lock:
                self.output_frame = draw_frame

            # For local video files, sleep to match natural video playback speed
            if is_file:
                elapsed = time.time() - current_time
                sleep_time = max(0.001, (1.0 / video_fps) - elapsed)
                time.sleep(sleep_time)

        cap.release()
        print("AI Counting Engine Stopped Safely.")
