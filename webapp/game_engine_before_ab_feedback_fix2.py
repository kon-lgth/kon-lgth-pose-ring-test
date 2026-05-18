"""
PoseRing web game engine.

This module adapts the current OpenCV/BLE/UDP game logic from
redlight_ring_2pc_main.py to a thread-safe Flask/Socket.IO backend.
The web UI owns presentation and browser audio; this engine owns cameras,
remote B-set UDP, BLE LED output, target capture, judging, and game state.
"""

import base64
import copy
import os
import sys
import threading
import time
from enum import Enum

import cv2
import numpy as np


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


COLOR_ORDER = ["RED", "YELLOW", "BLUE", "GREEN"]

DIFFICULTIES = {
    "easy": {"clear_dist_mm": 500.0, "hold_time": 1.5, "time_per_pose": 75},
    "medium": {"clear_dist_mm": 390.0, "hold_time": 2.0, "time_per_pose": 60},
    "hard": {"clear_dist_mm": 250.0, "hold_time": 3.0, "time_per_pose": 45},
}


class GameState(str, Enum):
    IDLE = "IDLE"
    COUNTDOWN = "COUNTDOWN"
    PLAYING = "PLAYING"
    POSE_CLEAR = "POSE_CLEAR"
    TIME_UP = "TIME_UP"
    ROUND_END = "ROUND_END"
    GAME_OVER = "GAME_OVER"
    GAME_CLEAR = "GAME_CLEAR"


def _vec_to_list(v):
    if v is None:
        return None
    return [float(x) for x in np.asarray(v).reshape(-1).tolist()]


def _encode_jpeg(frame):
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
    return buf.tobytes() if ok else None


def _blank_frame(label, width=640, height=240):
    img = np.full((height, width, 3), 24, dtype=np.uint8)
    cv2.putText(img, label, (20, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (120, 120, 120), 2)
    return img


def _camera_frame(frame, label):
    if frame is None:
        out = _blank_frame(label, height=480)
    else:
        out = cv2.resize(frame.copy(), (640, 480))
    cv2.rectangle(out, (0, 0), (360, 48), (0, 0, 0), -1)
    cv2.putText(out, label, (14, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.05, (255, 255, 255), 3)
    return out


class GameEngine:
    def __init__(self, settings):
        self._settings = dict(settings)
        self._lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._commands = []
        self._thread = None
        self._running = False
        self._snapshot_event = None
        self._jpeg = {0: None, 1: None, 2: None, 3: None}
        self._ble_status = {}
        self._live_error = None
        self._core = None
        self._current_pose = None

        self._apply_settings(self._settings)
        self._state = self._blank_state("Ready. Set targets, then start the game.")

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=4.0)

    def get_state(self):
        with self._lock:
            return copy.deepcopy(self._state)

    def get_frame(self, cam_id):
        with self._frame_lock:
            return self._jpeg.get(cam_id)

    def get_ble_status(self):
        with self._lock:
            return dict(self._ble_status)

    def get_current_pose_snapshot(self):
        with self._lock:
            return copy.deepcopy(self._current_pose)

    def pop_snapshot_event(self):
        with self._lock:
            event = self._snapshot_event
            self._snapshot_event = None
            return event

    def send_command(self, cmd, data=None):
        with self._lock:
            self._commands.append((cmd, data))

    def _apply_settings(self, settings):
        diff = DIFFICULTIES.get(settings.get("difficulty", "medium"), DIFFICULTIES["medium"])
        self._clear_dist = float(diff["clear_dist_mm"])
        self._hold_time = float(diff["hold_time"])
        self._time_per_pose = float(diff["time_per_pose"])
        if settings.get("vs_no_timeout"):
            self._time_per_pose = 9999.0
        self._poses_per_round = int(settings.get("poses_per_round", 5))
        self._num_rounds = int(settings.get("num_rounds", 3))
        self._players = list(settings.get("players", ["Player 1"])) or ["Player 1"]
        self._player_colors = dict(settings.get("player_colors", {}) or {})
        self._simulation = bool(settings.get("simulation", False))

    def _current_player(self, ctx):
        if not self._players:
            return None
        pose_index = int(ctx.get("pose", 0))
        if ctx.get("game_state") in (GameState.POSE_CLEAR, GameState.TIME_UP):
            pose_index = max(0, pose_index - 1)
        index = pose_index % len(self._players)
        return self._players[index]

    def _blank_colors(self):
        return {
            color: {
                "status": "NO DATA",
                "distance": None,
                "inside": False,
                "source": "NO DATA",
                "used_set": "-",
                "proximity": 0.0,
                "target": None,
                "current": None,
                "y_diff": None,
            }
            for color in COLOR_ORDER
        }

    def _blank_state(self, message):
        return {
            "game_state": GameState.IDLE.value,
            "round": 1,
            "pose": 0,
            "poses_per_round": self._poses_per_round,
            "num_rounds": self._num_rounds,
            "scores": {p: 0 for p in self._players},
            "players": list(self._players),
            "player_colors": dict(getattr(self, "_player_colors", {})),
            "current_player": self._current_player({"pose": 0}),
            "time_left": self._time_per_pose,
            "hold_progress": 0.0,
            "all_inside": False,
            "origin_set": True,
            "targets_set": False,
            "message": message,
            "difficulty": self._settings.get("difficulty", "medium"),
            "simulation": self._simulation,
            "countdown": None,
            "pose_result": None,
            "current_pose_name": None,
            "current_pose_difficulty": self._settings.get("difficulty", "medium"),
            "colors": self._blank_colors(),
            "ble": {},
            "live_error": self._live_error,
        }

    def _pop_commands(self):
        with self._lock:
            commands = self._commands[:]
            self._commands.clear()
            return commands

    def _capture_snapshots(self):
        snapshots = {}
        with self._frame_lock:
            for cam_id in (0, 1):
                jpeg = self._jpeg.get(cam_id)
                if jpeg:
                    snapshots[f"cam{cam_id}"] = base64.b64encode(jpeg).decode("ascii")
        return snapshots

    def _publish(self, ctx, colors):
        with self._lock:
            self._state = {
                "game_state": ctx["game_state"].value,
                "round": ctx["round"],
                "pose": ctx["pose"],
                "poses_per_round": self._poses_per_round,
                "num_rounds": self._num_rounds,
                "scores": dict(ctx["scores"]),
                "players": list(self._players),
                "player_colors": dict(getattr(self, "_player_colors", {})),
                "current_player": self._current_player(ctx),
                "time_left": ctx.get("time_left", self._time_per_pose),
                "hold_progress": ctx.get("hold_progress", 0.0),
                "all_inside": ctx.get("all_inside", False),
                "origin_set": True,
                "targets_set": ctx.get("targets_set", False),
                "message": ctx.get("message", ""),
                "difficulty": self._settings.get("difficulty", "medium"),
                "simulation": self._simulation,
                "countdown": ctx.get("countdown_n"),
                "pose_result": ctx.get("pose_result"),
                "current_pose_name": ctx.get("current_pose_name"),
                "current_pose_difficulty": ctx.get("current_pose_difficulty"),
                "colors": colors,
                "ble": dict(self._ble_status),
                "live_error": self._live_error,
            }

    def _run(self):
        if self._simulation:
            self._run_simulation()
            return

        try:
            self._run_live()
        except Exception as exc:
            self._live_error = str(exc)
            print(f"[WebEngine] Live mode failed, switching to simulation: {exc}")
            self._simulation = True
            self._run_simulation()

    def _configure_core(self):
        import redlight_ring_2pc_main as core

        self._core = core
        core.CLEAR_DISTANCE_MM = self._clear_dist
        core.HOLD_TIME_SEC = self._hold_time
        core.FEEDBACK_MAX_DISTANCE_MM = self._clear_dist * 3.0
        return core

    def _make_context(self):
        return {
            "game_state": GameState.IDLE,
            "round": 1,
            "pose": 0,
            "scores": {p: 0 for p in self._players},
            "all_inside_t": None,
            "pose_start_t": None,
            "transition_t": None,
            "countdown_n": None,
            "countdown_t": None,
            "pose_result": None,
            "poses_cleared_total": 0,
            "targets_set": False,
            "message": "Ready. Set targets, then start the game.",
            "time_left": self._time_per_pose,
            "hold_progress": 0.0,
            "all_inside": False,
            "clear_logged": False,
            "current_pose_name": None,
            "current_pose_difficulty": self._settings.get("difficulty", "medium"),
            "target_slots": [],
        }

    def _target_slots_from_pose_sets(self, sets, allowed_sets=None):
        allowed_sets = set(allowed_sets) if allowed_sets is not None else None
        slots = []
        for color in COLOR_ORDER:
            points = {}
            for set_name, set_points in (sets or {}).items():
                if allowed_sets is not None and set_name not in allowed_sets:
                    continue
                if not isinstance(set_points, dict):
                    continue
                point = set_points.get(color)
                if point is not None:
                    points[set_name] = np.array(point, dtype=np.float64)
            if points:
                slots.append({"source_color": color, "points": points})
        return slots

    def _target_slots_from_current_targets(self, set_a=None, set_b=None):
        slots = []
        for color in COLOR_ORDER:
            points = {}
            if set_a is not None:
                a_target = set_a.states[color].get("target")
                if a_target is not None:
                    points["A"] = np.array(a_target, dtype=np.float64)
            if set_b is not None:
                b_target = set_b.states[color].get("target")
                if b_target is not None:
                    points["B"] = np.array(b_target, dtype=np.float64)
            if points:
                slots.append({"source_color": color, "points": points})
        return slots

    def _current_points_from_sets(self, set_a=None, set_b=None):
        current = {color: {} for color in COLOR_ORDER}
        for color in COLOR_ORDER:
            if set_a is not None:
                st = set_a.states[color]
                point = st.get("live_point") if st.get("live") else st.get("current_point")
                if point is not None:
                    current[color]["A"] = {
                        "point": np.array(point, dtype=np.float64),
                        "source": "A_LIVE" if st.get("live") else "LAST_USED",
                        "y_diff": st.get("y_diff"),
                    }
            if set_b is not None:
                st = set_b.states[color]
                point = st.get("live_point") if st.get("live") else st.get("current_point")
                if point is not None:
                    current[color]["B"] = {
                        "point": np.array(point, dtype=np.float64),
                        "source": "B_LIVE" if st.get("live") else "LAST_USED",
                        "y_diff": st.get("y_diff"),
                    }
        return current

    def _current_points_from_color_state(self, colors):
        current = {color: {} for color in COLOR_ORDER}
        for color in COLOR_ORDER:
            point = (colors or {}).get(color, {}).get("current")
            if point is not None:
                current[color]["SIM"] = {
                    "point": np.array(point, dtype=np.float64),
                    "source": "SIM",
                    "y_diff": (colors or {}).get(color, {}).get("y_diff"),
                }
        return current

    def _target_distance_for_color(self, color_current, slot):
        best = None
        for set_name, target in slot.get("points", {}).items():
            cur = color_current.get(set_name)
            if not cur:
                continue
            distance = float(np.linalg.norm(cur["point"] - target))
            if best is None or distance < best["distance"]:
                best = {
                    "distance": distance,
                    "used_set": set_name,
                    "source": cur["source"],
                    "current": cur["point"],
                    "target": target,
                    "y_diff": cur.get("y_diff"),
                }
        return best

    def _solve_color_target_assignment(self, distance_matrix):
        best = {"count": -1, "distance": float("inf"), "assignment": {}}
        targets = list(range(len(distance_matrix)))

        def walk(target_index, used_colors, assignment, total_distance):
            assigned_count = len(assignment)
            if (
                assigned_count > best["count"]
                or (assigned_count == best["count"] and total_distance < best["distance"])
            ):
                best["count"] = assigned_count
                best["distance"] = total_distance
                best["assignment"] = dict(assignment)

            if target_index >= len(targets):
                return

            # Option 1: leave this target unmatched for partial progress display.
            walk(target_index + 1, used_colors, assignment, total_distance)

            # Option 2: assign one unused color to this target.
            for color in COLOR_ORDER:
                if color in used_colors:
                    continue
                distance = distance_matrix[target_index].get(color)
                if distance is None or distance > self._clear_dist:
                    continue
                assignment[color] = target_index
                used_colors.add(color)
                walk(target_index + 1, used_colors, assignment, total_distance + distance)
                used_colors.remove(color)
                assignment.pop(color, None)

        walk(0, set(), {}, 0.0)
        return best["assignment"]

    def _color_agnostic_colors(self, target_slots, current_by_color):
        colors = {}
        distance_matrix = []
        details_by_target = []

        for slot in target_slots:
            row = {}
            details = {}
            for color in COLOR_ORDER:
                detail = self._target_distance_for_color(current_by_color.get(color, {}), slot)
                if detail is not None:
                    row[color] = detail["distance"]
                    details[color] = detail
            distance_matrix.append(row)
            details_by_target.append(details)

        assignment = self._solve_color_target_assignment(distance_matrix)
        assigned_by_color = {color: target_index for color, target_index in assignment.items()}
        max_distance = max(self._clear_dist * 3.0, 1.0)

        for color in COLOR_ORDER:
            nearest = None
            nearest_index = None
            for target_index, details in enumerate(details_by_target):
                detail = details.get(color)
                if detail is None:
                    continue
                if nearest is None or detail["distance"] < nearest["distance"]:
                    nearest = detail
                    nearest_index = target_index

            assigned_index = assigned_by_color.get(color)
            if assigned_index is not None:
                nearest = details_by_target[assigned_index].get(color, nearest)
                nearest_index = assigned_index

            distance = nearest["distance"] if nearest is not None else None
            inside = assigned_index is not None
            proximity = 0.0 if distance is None else max(0.0, min(1.0, 1.0 - distance / max_distance))
            current = nearest["current"] if nearest is not None else None
            target = nearest["target"] if nearest is not None else None
            source = nearest["source"] if nearest is not None else "NO DATA"
            used_set = nearest["used_set"] if nearest is not None else "-"

            colors[color] = {
                "status": "OK" if inside else ("NO DATA" if current is None else ("CLOSE" if distance is not None and distance <= self._clear_dist * 2 else "FAR")),
                "distance": distance,
                "inside": inside,
                "source": source,
                "used_set": used_set,
                "proximity": proximity,
                "target": _vec_to_list(target),
                "current": _vec_to_list(current),
                "y_diff": nearest.get("y_diff") if nearest is not None else None,
                "target_index": None if nearest_index is None else nearest_index + 1,
                "matched_target_index": None if assigned_index is None else assigned_index + 1,
                "target_count": len(target_slots),
            }

        return colors

    def _set_targets_from_pose(self, pose, ctx, set_a=None, set_b=None):
        sets = (pose or {}).get("sets", {})

        if set_a is None:
            target_slots = self._target_slots_from_pose_sets(sets)
            ctx["target_slots"] = target_slots
            ctx["targets_set"] = bool(target_slots)
            ctx["current_pose_name"] = pose.get("name", "Saved pose")
            ctx["current_pose_difficulty"] = pose.get("difficulty", self._settings.get("difficulty", "medium"))
            ctx["message"] = (
                f"Loaded pose: {ctx['current_pose_name']}"
                if target_slots
                else "Pose is missing target point data."
            )
            return

        allowed_sets = {"A"}
        if set_b is not None:
            allowed_sets.add("B")
        target_slots = self._target_slots_from_pose_sets(sets, allowed_sets)

        for color in COLOR_ORDER:
            a_point = sets.get("A", {}).get(color)
            b_point = sets.get("B", {}).get(color)

            set_a.states[color]["target"] = np.array(a_point, dtype=np.float64) if a_point is not None else None
            if set_b is not None:
                set_b.states[color]["target"] = np.array(b_point, dtype=np.float64) if b_point is not None else None

        difficulty = pose.get("difficulty", self._settings.get("difficulty", "medium"))
        self._settings["difficulty"] = difficulty
        self._apply_settings(self._settings)
        self._configure_core()

        ctx["target_slots"] = target_slots
        ctx["targets_set"] = bool(target_slots)
        ctx["current_pose_name"] = pose.get("name", "Saved pose")
        ctx["current_pose_difficulty"] = difficulty
        ctx["game_state"] = GameState.IDLE
        ctx["pose_result"] = None
        ctx["all_inside_t"] = None
        ctx["hold_progress"] = 0.0
        ctx["message"] = (
            f"Loaded pose: {ctx['current_pose_name']}"
            if target_slots
            else "Pose is missing target point data."
        )

    def _update_current_pose_cache(self, set_a=None, set_b=None, colors=None):
        if set_a is None:
            sets = {
                "SIM": {
                    color: colors[color]["current"]
                    for color in COLOR_ORDER
                    if colors and colors.get(color, {}).get("current") is not None
                }
            }
        else:
            sets = {"A": {}, "B": {}}
            for color in COLOR_ORDER:
                sets["A"][color] = _vec_to_list(set_a.states[color].get("current_point"))
                if set_b is not None:
                    sets["B"][color] = _vec_to_list(set_b.states[color].get("current_point"))

        with self._lock:
            self._current_pose = {
                "sets": sets,
                "captured_at": time.time(),
                "source": "simulation" if set_a is None else "live",
            }

    def _process_commands(self, commands, ctx, set_a=None, set_b=None):
        for cmd, data in commands:
            if cmd == "start_game":
                if data:
                    self._settings.update(data)
                    self._apply_settings(self._settings)
                    for name in list(ctx["scores"]):
                        if name not in self._players:
                            ctx["scores"].pop(name, None)
                    for name in self._players:
                        ctx["scores"].setdefault(name, 0)

                if not ctx.get("targets_set", False):
                    ctx["message"] = "Set the target pose first."
                    continue

                ctx["game_state"] = GameState.COUNTDOWN
                ctx["countdown_n"] = 3
                ctx["countdown_t"] = time.time()
                ctx["pose_start_t"] = None
                ctx["all_inside_t"] = None
                ctx["pose_result"] = None
                pose_name = ctx.get("current_pose_name") or "Current pose"
                ctx["message"] = f"Pose: {pose_name}"

            elif cmd == "set_origin":
                ctx["message"] = "Origin is implicit in the saved A/B target coordinates."

            elif cmd == "set_targets":
                if set_a is None:
                    ctx["targets_set"] = True
                    ctx["target_slots"] = []
                    ctx["current_pose_name"] = "Manual simulation pose"
                    ctx["current_pose_difficulty"] = self._settings.get("difficulty", "medium")
                    ctx["message"] = "Simulation target pose saved. Press START."
                    continue

                saved_a, missing_a = set_a.set_targets_from_current()
                saved_b, missing_b = ([], COLOR_ORDER.copy())
                if set_b is not None:
                    saved_b, missing_b = set_b.set_targets_from_current()

                target_slots = self._target_slots_from_current_targets(set_a, set_b)

                ctx["target_slots"] = target_slots
                ctx["targets_set"] = bool(target_slots)
                ctx["game_state"] = GameState.IDLE
                ctx["pose_result"] = None
                ctx["all_inside_t"] = None
                ctx["hold_progress"] = 0.0
                if target_slots:
                    ctx["current_pose_name"] = "Manual target pose"
                    ctx["current_pose_difficulty"] = self._settings.get("difficulty", "medium")
                    ctx["message"] = f"{len(target_slots)} target points saved. Press START."
                else:
                    ctx["message"] = "No visible target points were saved."

                print(f"[WebEngine] targets saved A={saved_a} missingA={missing_a} B={saved_b} missingB={missing_b}")

            elif cmd == "load_pose" and data:
                self._set_targets_from_pose(data, ctx, set_a, set_b)

            elif cmd == "next_pose":
                if ctx["game_state"] not in (GameState.POSE_CLEAR, GameState.TIME_UP):
                    continue

                if ctx["pose"] >= self._poses_per_round:
                    ctx["game_state"] = GameState.ROUND_END
                    ctx["transition_t"] = time.time() + 2.0
                    ctx["message"] = f"Round {ctx['round']} complete."
                else:
                    ctx["game_state"] = GameState.IDLE
                    ctx["message"] = "Set the next target pose."

                ctx["targets_set"] = False
                ctx["target_slots"] = []
                ctx["all_inside_t"] = None
                ctx["hold_progress"] = 0.0
                if set_a is not None:
                    set_a.reset_targets()
                if set_b is not None:
                    set_b.reset_targets()

            elif cmd == "reset":
                ctx.update(self._make_context())
                if set_a is not None:
                    set_a.reset_targets()
                if set_b is not None:
                    set_b.reset_targets()

    def _tick_game(self, ctx, colors):
        now = time.time()

        if ctx["game_state"] == GameState.ROUND_END and now >= ctx.get("transition_t", now + 99):
            ctx["round"] += 1
            ctx["pose"] = 0
            if ctx["round"] > self._num_rounds:
                total = self._num_rounds * self._poses_per_round
                ctx["game_state"] = (
                    GameState.GAME_CLEAR
                    if ctx.get("poses_cleared_total", 0) >= total
                    else GameState.GAME_OVER
                )
                ctx["message"] = "GAME CLEAR!" if ctx["game_state"] == GameState.GAME_CLEAR else "GAME OVER."
            else:
                ctx["game_state"] = GameState.IDLE
                ctx["message"] = f"Round {ctx['round']}. Set the next target pose."

        targets_set = bool(ctx.get("targets_set", False))
        target_count = len(ctx.get("target_slots") or [])
        matched_count = len({
            colors[color].get("matched_target_index")
            for color in COLOR_ORDER
            if colors[color].get("matched_target_index") is not None
        })
        all_inside = (
            targets_set
            and (
                (target_count > 0 and matched_count >= target_count)
                or (target_count == 0 and all(colors[color]["inside"] for color in COLOR_ORDER))
            )
        )
        ctx["all_inside"] = all_inside
        ctx["time_left"] = self._time_per_pose
        ctx["hold_progress"] = 0.0

        if ctx["game_state"] == GameState.COUNTDOWN:
            n = ctx.get("countdown_n", 3)
            if now - ctx.get("countdown_t", now) >= 1.0:
                n -= 1
                ctx["countdown_t"] = now
                if n <= 0:
                    ctx["game_state"] = GameState.PLAYING
                    ctx["pose_start_t"] = now
                    ctx["countdown_n"] = 0
                    ctx["message"] = "GO!"
                else:
                    ctx["countdown_n"] = n
                    pose_name = ctx.get("current_pose_name") or "Current pose"
                    ctx["message"] = f"Pose: {pose_name}"

        elif ctx["game_state"] == GameState.PLAYING:
            elapsed = now - ctx.get("pose_start_t", now)
            time_left = max(0.0, self._time_per_pose - elapsed)
            ctx["time_left"] = time_left

            if all_inside:
                if ctx["all_inside_t"] is None:
                    ctx["all_inside_t"] = now
                hold_elapsed = now - ctx["all_inside_t"]
                ctx["hold_progress"] = min(1.0, hold_elapsed / self._hold_time)
                ctx["message"] = f"HOLD {hold_elapsed:.1f}/{self._hold_time:.1f}s"

                if hold_elapsed >= self._hold_time:
                    current_player = self._current_player(ctx)
                    ctx["pose"] += 1
                    ctx["pose_result"] = "cleared"
                    ctx["poses_cleared_total"] += 1
                    ctx["game_state"] = GameState.POSE_CLEAR
                    ctx["message"] = "POSE CLEAR. Tap NEXT when ready."
                    speed_bonus = max(0, int((time_left / self._time_per_pose) * 50))
                    points = 100 * ctx["round"] + speed_bonus
                    if current_player:
                        ctx["scores"][current_player] = ctx["scores"].get(current_player, 0) + points
                    self._queue_snapshot(ctx)
            else:
                ctx["all_inside_t"] = None
                pose_name = ctx.get("current_pose_name")
                ctx["message"] = (
                    f"Explore: {pose_name}"
                    if pose_name
                    else "Explore. Follow the bracelet feedback."
                )

            if (
                time_left <= 0
                and ctx["game_state"] == GameState.PLAYING
                and not self._settings.get("vs_no_timeout")
            ):
                ctx["pose"] += 1
                ctx["pose_result"] = "timeout"
                ctx["game_state"] = GameState.TIME_UP
                ctx["message"] = "TIME'S UP. Tap NEXT when ready."
                self._queue_snapshot(ctx)

        elif ctx["game_state"] == GameState.POSE_CLEAR:
            ctx["time_left"] = 0
            ctx["message"] = "POSE CLEAR. Tap NEXT when ready."

        elif ctx["game_state"] == GameState.TIME_UP:
            ctx["time_left"] = 0
            ctx["message"] = "TIME'S UP. Tap NEXT when ready."

        elif ctx["game_state"] in (GameState.GAME_CLEAR, GameState.GAME_OVER):
            ctx["time_left"] = 0

    def _queue_snapshot(self, ctx):
        event = {
            **self._capture_snapshots(),
            "result": ctx.get("pose_result", "unknown"),
            "round": ctx["round"],
            "pose": ctx["pose"],
        }
        with self._lock:
            self._snapshot_event = event

    def _status_from_final(self, final_state):
        if final_state["distance"] is None:
            return "NO DATA" if final_state["current"] is None else "NO TARGET"
        if final_state["inside"]:
            return "OK"
        if final_state["distance"] <= self._clear_dist * 2:
            return "CLOSE"
        return "FAR"

    def _colors_from_final(self, final_states):
        colors = {}
        max_distance = max(self._clear_dist * 3.0, 1.0)
        for color in COLOR_ORDER:
            fs = final_states[color]
            distance = fs.get("distance")
            proximity = 0.0 if distance is None else max(0.0, min(1.0, 1.0 - distance / max_distance))
            colors[color] = {
                "status": self._status_from_final(fs),
                "distance": distance,
                "inside": bool(fs.get("inside", False)),
                "source": fs.get("source", "NO DATA"),
                "used_set": fs.get("used_set", "-"),
                "proximity": proximity,
                "target": _vec_to_list(fs.get("target")),
                "current": _vec_to_list(fs.get("current")),
                "y_diff": fs.get("y_diff"),
            }
        return colors


    def _make_multi_ble_feedbacks(self, core):
        """Create one BLE feedback controller per PoseRing color."""
        char_uuid = self._settings.get("ble_char_uuid", core.BLE_LED_CHAR_UUID)
        device_names = {
            "RED": os.getenv("POSERING_BLE_RED", self._settings.get("ble_red_device_name", "PoseRing_RED")),
            "YELLOW": os.getenv("POSERING_BLE_YELLOW", self._settings.get("ble_yellow_device_name", "PoseRing_YELLOW")),
            "BLUE": os.getenv("POSERING_BLE_BLUE", self._settings.get("ble_blue_device_name", "PoseRing_BLUE")),
            "GREEN": os.getenv("POSERING_BLE_GREEN", self._settings.get("ble_green_device_name", "PoseRing_GREEN")),
        }

        feedbacks = {}
        for color, device_name in device_names.items():
            controller = core.BleFeedbackController(device_name, char_uuid)
            controller.start()
            try:
                controller.set_state(core.BleFeedbackController.STATE_OFF)
            except Exception:
                pass
            feedbacks[color] = controller
        return feedbacks

    def _is_live_marker_source(self, source):
        return source in ["A_LIVE", "B_LIVE", "SIM"]

    def _target_distance_for_color_ble(self, color_current, slot, *, allow_sources=None):
        """Return nearest valid target distance for BLE feedback.

        Unlike the game judging path, this intentionally ignores LAST_USED data.
        This fixes the case where a marker is hidden from A but visible from B:
        the BLE ring must follow the B_LIVE distance instead of seeing stale A
        coordinates and turning off.
        """
        best = None
        allow_sources = set(allow_sources or ["A_LIVE", "B_LIVE", "SIM"])
        for set_name, target in (slot.get("points", {}) or {}).items():
            cur = (color_current or {}).get(set_name)
            if not cur:
                continue
            source = cur.get("source")
            if source not in allow_sources:
                continue
            try:
                cur_point = np.array(cur.get("point"), dtype=np.float64).reshape(-1)[:3]
                target_point = np.array(target, dtype=np.float64).reshape(-1)[:3]
            except (TypeError, ValueError):
                continue
            if cur_point.size < 3 or target_point.size < 3:
                continue
            if not (np.all(np.isfinite(cur_point)) and np.all(np.isfinite(target_point))):
                continue
            distance = float(np.linalg.norm(cur_point - target_point))
            if best is None or distance < best["distance"]:
                best = {
                    "distance": distance,
                    "used_set": set_name,
                    "source": source,
                    "current": cur_point,
                    "target": target_point,
                    "y_diff": cur.get("y_diff"),
                }
        return best

    def _nearest_target_ble_states_with_occupancy(self, target_slots, current_by_color, raw_final_states=None, ble_claims=None):
        """Calculate per-ring BLE feedback using A/B live coordinates.

        Game clear judging remains color-agnostic. This function is only for LED
        feedback. If one color occupies a goal, that goal is hidden from other
        colors, so later entrants are guided to the next nearest unoccupied goal
        instead of blinking on the already occupied one.
        """
        ble_claims = ble_claims if ble_claims is not None else {}
        release_distance = float(self._clear_dist * 1.35)
        max_distance = max(self._clear_dist * 3.0, 1.0)
        target_slots = list(target_slots or [])

        # Precompute live-only distance details: target_index -> color -> detail.
        details_by_target = []
        for slot in target_slots:
            details = {}
            for color in COLOR_ORDER:
                detail = self._target_distance_for_color_ble(
                    (current_by_color or {}).get(color, {}),
                    slot,
                    allow_sources=["A_LIVE", "B_LIVE", "SIM"],
                )
                if detail is not None:
                    details[color] = detail
            details_by_target.append(details)

        # Normalize and release old claims when the owner is gone or far enough.
        claims = {}
        for target_index, owner in list((ble_claims or {}).items()):
            try:
                target_index = int(target_index)
            except (TypeError, ValueError):
                continue
            if owner not in COLOR_ORDER or not (0 <= target_index < len(details_by_target)):
                continue
            detail = details_by_target[target_index].get(owner)
            if detail is None or detail["distance"] > release_distance:
                continue
            claims[target_index] = owner

        # Existing owners keep their goals. Then free goals can be claimed by the
        # nearest unused live color inside the clear distance.
        used_colors = set(claims.values())
        candidates = []
        for target_index, details in enumerate(details_by_target):
            if target_index in claims:
                continue
            for color, detail in details.items():
                if color in used_colors:
                    continue
                if detail["distance"] <= self._clear_dist:
                    candidates.append((detail["distance"], target_index, color))

        for _distance, target_index, color in sorted(candidates, key=lambda item: item[0]):
            if target_index in claims or color in used_colors:
                continue
            claims[target_index] = color
            used_colors.add(color)

        if ble_claims is not None:
            ble_claims.clear()
            ble_claims.update(claims)

        states = {}
        for color in COLOR_ORDER:
            nearest = None
            nearest_index = None
            owned_index = None
            for target_index, owner in claims.items():
                if owner == color:
                    owned_index = target_index
                    break

            # If this color owns a goal, keep using that goal so it continues to blink.
            if owned_index is not None:
                nearest = details_by_target[owned_index].get(color)
                nearest_index = owned_index

            # Otherwise choose nearest goal that is not occupied by another color.
            if nearest is None:
                for target_index, details in enumerate(details_by_target):
                    owner = claims.get(target_index)
                    if owner is not None and owner != color:
                        continue
                    detail = details.get(color)
                    if detail is None:
                        continue
                    if nearest is None or detail["distance"] < nearest["distance"]:
                        nearest = detail
                        nearest_index = target_index

            if nearest is not None:
                distance = nearest["distance"]
                inside = bool(
                    nearest_index is not None
                    and claims.get(nearest_index) == color
                    and distance <= self._clear_dist
                )
                proximity = max(0.0, min(1.0, 1.0 - distance / max_distance))
                states[color] = {
                    "used_set": nearest.get("used_set", "-"),
                    "source": nearest.get("source", "NO DATA"),
                    "current": nearest.get("current"),
                    "target": nearest.get("target"),
                    "distance": distance,
                    "inside": inside,
                    "y_diff": nearest.get("y_diff"),
                    "proximity": proximity,
                    "target_index": None if nearest_index is None else nearest_index + 1,
                    "occupied_by": claims.get(nearest_index) if nearest_index is not None else None,
                    "ble_claims": {str(k + 1): v for k, v in claims.items()},
                }
            else:
                raw = ((raw_final_states or {}).get(color) or {})
                states[color] = {
                    "used_set": raw.get("used_set", "-"),
                    "source": raw.get("source", "NO DATA"),
                    "current": raw.get("current"),
                    "target": None,
                    "distance": None,
                    "inside": False,
                    "y_diff": raw.get("y_diff"),
                    "proximity": 0.0,
                    "target_index": None,
                    "occupied_by": None,
                    "ble_claims": {str(k + 1): v for k, v in claims.items()},
                }
        return states

    def _update_multi_ble_status_connect_only(self, core, feedbacks):
        if not feedbacks:
            with self._lock:
                self._ble_status = {"enabled": False, "mode": "multi_connect_only"}
            return

        rings = {}
        for color, controller in feedbacks.items():
            rings[color] = {
                "device": controller.device_name,
                "connected": bool(controller.is_connected),
                "value": int(core.BleFeedbackController.STATE_OFF),
            }

        with self._lock:
            self._ble_status = {
                "enabled": True,
                "mode": "multi_connect_only",
                "connected": any(r["connected"] for r in rings.values()),
                "rings": rings,
            }

    def _update_multi_ble_visible_white(self, core, feedbacks, final_states):
        if not feedbacks:
            with self._lock:
                self._ble_status = {"enabled": False, "mode": "multi_visible_white"}
            return

        rings = {}
        for color, controller in feedbacks.items():
            fs = (final_states or {}).get(color, {})
            visible = bool(fs.get("current") is not None and self._is_live_marker_source(fs.get("source")))
            value = core.BleFeedbackController.STATE_CONNECTED_WHITE if visible else core.BleFeedbackController.STATE_OFF
            try:
                controller.set_state(value)
            except Exception:
                pass
            rings[color] = {
                "device": controller.device_name,
                "connected": bool(controller.is_connected),
                "visible": visible,
                "source": fs.get("source", "NO DATA"),
                "value": int(value),
            }

        with self._lock:
            self._ble_status = {
                "enabled": True,
                "mode": "multi_visible_white",
                "connected": any(r["connected"] for r in rings.values()),
                "rings": rings,
            }

    def _update_multi_ble_distance_feedback(self, core, ctx, feedbacks, final_states):
        """Send per-color distance feedback to each physical ring.

        Uses final_states prepared by _nearest_target_ble_states_with_occupancy(),
        so A-hidden/B-live markers still receive B-set distance feedback.
        """
        if not feedbacks:
            with self._lock:
                self._ble_status = {"enabled": False, "mode": "multi_distance_feedback"}
            return

        # POSE_CLEAR: RED gets 251 once for sound. Connected rings then get 252.
        if ctx.get("game_state") == GameState.POSE_CLEAR:
            clear_key = (ctx.get("round"), ctx.get("pose"), ctx.get("current_pose_name"))
            if ctx.get("multi_ble_clear_key") != clear_key:
                ctx["multi_ble_clear_key"] = clear_key
                ctx["multi_ble_clear_sound_sent"] = False

            rings = {}
            for color, controller in feedbacks.items():
                value = 252
                reason = "clear_solid"
                if color == "RED" and not ctx.get("multi_ble_clear_sound_sent", False):
                    value = 251
                    reason = "clear_sound"
                    ctx["multi_ble_clear_sound_sent"] = True
                try:
                    controller.set_state(value)
                except Exception:
                    pass
                fs = (final_states or {}).get(color, {}) or {}
                rings[color] = {
                    "device": controller.device_name,
                    "connected": bool(controller.is_connected),
                    "visible": bool(fs.get("current") is not None),
                    "source": fs.get("source", "NO DATA"),
                    "value": int(value),
                    "reason": reason,
                    "distance": None,
                    "target_index": fs.get("target_index"),
                }
            with self._lock:
                self._ble_status = {
                    "enabled": True,
                    "mode": "multi_distance_feedback",
                    "connected": any(r["connected"] for r in rings.values()),
                    "rings": rings,
                }
            return
        else:
            ctx["multi_ble_clear_key"] = None
            ctx["multi_ble_clear_sound_sent"] = False

        rings = {}
        for color, controller in feedbacks.items():
            fs = (final_states or {}).get(color, {}) or {}
            visible = bool(fs.get("current") is not None and self._is_live_marker_source(fs.get("source")))
            distance = fs.get("distance")

            if not visible:
                value = core.BleFeedbackController.STATE_OFF
                reason = "not_visible"
            elif ctx.get("game_state") != GameState.PLAYING or not ctx.get("targets_set", False):
                value = core.BleFeedbackController.STATE_CONNECTED_WHITE
                reason = "visible_not_playing"
            elif distance is None:
                value = core.BleFeedbackController.STATE_CONNECTED_WHITE
                reason = "visible_no_distance"
            elif fs.get("inside", False):
                value = 250
                reason = "inside_own_goal"
            else:
                value = int(core.distance_to_red_brightness(distance))
                value = max(2, min(249, value))
                reason = "distance_feedback"

            try:
                controller.set_state(value)
            except Exception:
                pass

            rings[color] = {
                "device": controller.device_name,
                "connected": bool(controller.is_connected),
                "visible": visible,
                "source": fs.get("source", "NO DATA"),
                "used_set": fs.get("used_set", "-"),
                "value": int(value),
                "reason": reason,
                "distance": None if distance is None else float(distance),
                "inside": bool(fs.get("inside", False)),
                "target_index": fs.get("target_index"),
                "occupied_by": fs.get("occupied_by"),
                "ble_claims": fs.get("ble_claims"),
            }

        with self._lock:
            self._ble_status = {
                "enabled": True,
                "mode": "multi_distance_feedback",
                "connected": any(r["connected"] for r in rings.values()),
                "rings": rings,
            }

    def _stop_multi_ble_feedbacks(self, core, feedbacks):
        if not feedbacks:
            return
        for controller in feedbacks.values():
            try:
                controller.set_state(core.BleFeedbackController.STATE_OFF)
            except Exception:
                pass
        time.sleep(0.2)
        for controller in feedbacks.values():
            try:
                controller.stop()
            except Exception:
                pass

    def _update_ble(self, core, ctx, final_states, ble_feedback, last_target_live_time):
        if ble_feedback is None:
            self._ble_status = {"enabled": False}
            return last_target_live_time

        target_color = self._settings.get("feedback_target_color", core.FEEDBACK_TARGET_COLOR)
        target_state = final_states.get(target_color)
        stage_now = time.time()
        target_live = bool(target_state and target_state["source"] in ["A_LIVE", "B_LIVE"])

        if target_live:
            last_target_live_time = stage_now
            stage_visible = True
            lost_age = 0.0
        elif last_target_live_time is None:
            stage_visible = False
            lost_age = None
        else:
            lost_age = stage_now - last_target_live_time
            stage_visible = lost_age <= core.STAGE_LOST_GRACE_SEC

        red_brightness = None
        if (
            ctx["game_state"] == GameState.PLAYING
            and ctx.get("targets_set", False)
            and stage_visible
            and target_state
            and target_state["distance"] is not None
        ):
            red_brightness = (
                core.FEEDBACK_MAX_RED_BRIGHTNESS
                if target_state["inside"]
                else core.distance_to_red_brightness(target_state["distance"])
            )

        if not stage_visible:
            value = core.BleFeedbackController.STATE_OFF
        elif red_brightness is None:
            value = core.BleFeedbackController.STATE_CONNECTED_WHITE
        else:
            value = max(core.BleFeedbackController.MIN_RED_BRIGHTNESS_VALUE, min(255, int(red_brightness)))

        ble_feedback.set_state(value)
        self._ble_status = {
            "enabled": True,
            "connected": bool(ble_feedback.is_connected),
            "device": ble_feedback.device_name,
            "target_color": target_color,
            "value": int(value),
            "stage_visible": bool(stage_visible),
            "lost_age": lost_age,
        }
        return last_target_live_time

    def _run_live(self):
        core = self._configure_core()

        a_calib = self._settings.get("a_calib_file") or core.A_CALIB_FILE
        b_calib = self._settings.get("b_calib_file") or core.B_CALIB_FILE
        use_b_set = bool(self._settings.get("use_b_set", core.USE_B_SET))
        use_remote_b_set = bool(self._settings.get("use_remote_b_set", core.USE_REMOTE_B_SET))

        set_a = core.StereoSet(
            "A",
            a_calib,
            int(self._settings.get("a_cam0_index", core.A_CAM0_INDEX)),
            int(self._settings.get("a_cam1_index", core.A_CAM1_INDEX)),
            self._settings.get("a_backend", core.A_BACKEND),
        )

        set_b = None
        if use_b_set:
            if use_remote_b_set:
                set_b = core.RemoteBSet(
                    "B",
                    self._settings.get("remote_b_udp_ip", core.REMOTE_B_UDP_IP),
                    int(self._settings.get("remote_b_udp_port", core.REMOTE_B_UDP_PORT)),
                )
            else:
                set_b = core.StereoSet(
                    "B",
                    b_calib,
                    int(self._settings.get("b_cam0_index", core.B_CAM0_INDEX)),
                    int(self._settings.get("b_cam1_index", core.B_CAM1_INDEX)),
                    self._settings.get("b_backend", core.B_BACKEND),
                )

        ble_feedback = None
        multi_ble_feedbacks = None
        ble_mode = os.getenv("POSERING_BLE_MODE", self._settings.get("ble_mode", "single")).strip().lower()
        if bool(self._settings.get("ble_enabled", core.ENABLE_XIAO_BLE)):
            if ble_mode in ["multi", "multi_connect", "multi_connect_only", "multi_visible", "multi_visible_white", "multi_stage_white", "multi_distance", "multi_distance_feedback"]:
                multi_ble_feedbacks = self._make_multi_ble_feedbacks(core)
                self._update_multi_ble_status_connect_only(core, multi_ble_feedbacks)
            else:
                ble_feedback = core.BleFeedbackController(
                    self._settings.get("ble_device_name", core.BLE_DEVICE_NAME),
                    self._settings.get("ble_char_uuid", core.BLE_LED_CHAR_UUID),
                )
                ble_feedback.start()

        ctx = self._make_context()
        last_used = {color: None for color in COLOR_ORDER}
        last_target_live_time = None

        try:
            while self._running:
                set_a.read_and_process()
                if set_b is not None:
                    set_b.read_and_process()

                self._process_commands(self._pop_commands(), ctx, set_a, set_b)

                raw_final_states = {}
                for color in COLOR_ORDER:
                    raw_final_states[color] = core.select_and_judge_color(color, set_a, set_b, last_used)

                current_by_color = self._current_points_from_sets(set_a, set_b)
                ble_states = raw_final_states

                if ctx.get("target_slots"):
                    target_slots = ctx.get("target_slots") or []
                    colors = self._color_agnostic_colors(target_slots, current_by_color)
                    # BLE feedback uses live A/B coordinates independently from
                    # the game assignment. Other colors cannot see a goal that is
                    # already occupied for BLE blinking, but B_LIVE coordinates are
                    # still used when A is hidden.
                    ble_states = self._nearest_target_ble_states_with_occupancy(
                        target_slots,
                        current_by_color,
                        raw_final_states,
                        ctx.setdefault("ble_target_claims", {}),
                    )
                else:
                    colors = self._colors_from_final(raw_final_states)
                    ctx.setdefault("ble_target_claims", {}).clear()
                self._update_current_pose_cache(set_a, set_b)
                self._tick_game(ctx, colors)
                if multi_ble_feedbacks is not None:
                    if ble_mode in ["multi_distance", "multi_distance_feedback"]:
                        self._update_multi_ble_distance_feedback(core, ctx, multi_ble_feedbacks, ble_states)
                    elif ble_mode in ["multi_visible", "multi_visible_white", "multi_stage_white"]:
                        self._update_multi_ble_visible_white(core, multi_ble_feedbacks, raw_final_states)
                    else:
                        self._update_multi_ble_status_connect_only(core, multi_ble_feedbacks)
                else:
                    last_target_live_time = self._update_ble(
                        core, ctx, raw_final_states, ble_feedback, last_target_live_time
                    )

                with self._frame_lock:
                    self._jpeg[0] = _encode_jpeg(_camera_frame(set_a.out0, f"A CAM {set_a.cam0_index}"))
                    self._jpeg[1] = _encode_jpeg(_camera_frame(set_a.out1, f"A CAM {set_a.cam1_index}"))
                    if set_b is not None and hasattr(set_b, "out0"):
                        self._jpeg[2] = _encode_jpeg(_camera_frame(set_b.out0, f"B CAM {set_b.cam0_index}"))
                        self._jpeg[3] = _encode_jpeg(_camera_frame(set_b.out1, f"B CAM {set_b.cam1_index}"))
                    elif set_b is not None:
                        remote_frame = set_b.make_display_pair()
                        self._jpeg[2] = _encode_jpeg(_camera_frame(remote_frame, "B UDP DATA"))
                        self._jpeg[3] = _encode_jpeg(_camera_frame(remote_frame, "B UDP DATA"))
                    else:
                        self._jpeg[2] = _encode_jpeg(_blank_frame("B SET disabled", height=480))
                        self._jpeg[3] = _encode_jpeg(_blank_frame("B SET disabled", height=480))

                self._publish(ctx, colors)
                time.sleep(0.01)

        finally:
            if multi_ble_feedbacks is not None:
                self._stop_multi_ble_feedbacks(core, multi_ble_feedbacks)
            if ble_feedback is not None:
                ble_feedback.set_state(core.BleFeedbackController.STATE_OFF)
                time.sleep(0.2)
                ble_feedback.stop()
            set_a.release()
            if set_b is not None:
                set_b.release()

    def _run_simulation(self):
        ctx = self._make_context()
        last_snapshot_state = None
        with self._frame_lock:
            self._jpeg[0] = _encode_jpeg(_blank_frame("SIM A CAM 0", height=480))
            self._jpeg[1] = _encode_jpeg(_blank_frame("SIM A CAM 1", height=480))
            self._jpeg[2] = _encode_jpeg(_blank_frame("SIM B CAM 0", height=480))
            self._jpeg[3] = _encode_jpeg(_blank_frame("SIM B CAM 1", height=480))

        while self._running:
            self._process_commands(self._pop_commands(), ctx)

            now = time.time()
            colors = {}
            for i, color in enumerate(COLOR_ORDER):
                distance = 180.0 + 180.0 * np.sin(now * 0.7 + i * 1.8)
                inside = bool(distance <= self._clear_dist)
                colors[color] = {
                    "status": "OK" if inside else ("CLOSE" if distance <= self._clear_dist * 2 else "FAR"),
                    "distance": float(abs(distance)),
                    "inside": inside,
                    "source": "SIM",
                    "used_set": "SIM",
                    "proximity": max(0.0, min(1.0, 1.0 - abs(distance) / (self._clear_dist * 3.0))),
                    "target": [100.0 * i, 50.0, 200.0],
                    "current": [100.0 * i + distance, 50.0, 200.0],
                    "y_diff": 0.0,
                }

            if ctx.get("target_slots"):
                colors = self._color_agnostic_colors(
                    ctx.get("target_slots") or [],
                    self._current_points_from_color_state(colors),
                )

            self._tick_game(ctx, colors)
            self._update_current_pose_cache(colors=colors)
            self._ble_status = {"enabled": False, "simulation": True}

            if ctx["game_state"] in (GameState.POSE_CLEAR, GameState.TIME_UP):
                marker = (ctx["game_state"], ctx["round"], ctx["pose"])
                if marker != last_snapshot_state:
                    self._queue_snapshot(ctx)
                    last_snapshot_state = marker
            else:
                last_snapshot_state = None

            self._publish(ctx, colors)
            time.sleep(0.05)
