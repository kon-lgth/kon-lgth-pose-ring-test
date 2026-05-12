"""
PoseRing Web Server
===================
Run with:
    cd webapp
    python server.py

Then open:
    http://localhost:5000          — welcome / home
    http://localhost:5000/player   — player screen  (open on TV / tablet)
    http://localhost:5000/operator — operator screen (game master)

Any number of browsers can connect simultaneously; all receive the same
live game state via Socket.IO.

Configuration
-------------
Edit the CONFIG block below, or pass settings through the web UI.
"""

import os
import sys
import time
import json
import uuid
import logging

import cv2
from flask import Flask, Response, render_template, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit

# Allow importing this webapp package when server.py is run directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_engine import GameEngine, DIFFICULTIES


def _env_bool(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


# ---------------------------------------------------------------------------
# Configuration — edit here or through the web UI
# ---------------------------------------------------------------------------

CONFIG = {
    # Set to True to run without cameras (great for UI development)
    "simulation": _env_bool("POSERING_SIMULATION", False),

    # A-set cameras on the main PC. Keep these aligned with redlight_ring_2pc_main.py.
    "a_cam0_index": _env_int("POSERING_A_CAM0", 1),
    "a_cam1_index": _env_int("POSERING_A_CAM1", 2),
    "a_backend": os.getenv("POSERING_A_BACKEND", "DEFAULT"),
    "a_calib_file": os.getenv("POSERING_A_CALIB", ""),

    # B-set can be read locally or received from the sub PC over UDP.
    "use_b_set": _env_bool("POSERING_USE_B_SET", True),
    "use_remote_b_set": _env_bool("POSERING_USE_REMOTE_B", True),
    "b_cam0_index": _env_int("POSERING_B_CAM0", 4),
    "b_cam1_index": _env_int("POSERING_B_CAM1", 5),
    "b_backend": os.getenv("POSERING_B_BACKEND", "DSHOW"),
    "b_calib_file": os.getenv("POSERING_B_CALIB", ""),
    "remote_b_udp_ip": os.getenv("POSERING_REMOTE_B_IP", "0.0.0.0"),
    "remote_b_udp_port": _env_int("POSERING_REMOTE_B_PORT", 5005),

    # Default game settings (overridable from the web UI)
    "players":        ["Player 1", "Player 2"],
    "difficulty":     "medium",
    "poses_per_round": 5,
    "num_rounds":      3,

    # XIAO nRF52840 / NeoPixel / DFPlayer firmware.
    # Uses BleFeedbackController from redlight_ring_2pc_main.py.
    "ble_enabled":     _env_bool("POSERING_BLE", True),
    "ble_device_name": os.getenv("POSERING_BLE_DEVICE", "PoseRing_YELLOW"),
    "ble_char_uuid":   os.getenv("POSERING_BLE_CHAR_UUID", "19B10001-E8F2-537E-4F6C-D104768A1214"),
    "feedback_target_color": os.getenv("POSERING_FEEDBACK_COLOR", "RED"),

    # Server
    # macOS uses port 5000 for AirPlay Receiver — use 5001 on Mac.
    # On Windows (presentation PC) port 5000 is free, change back if needed.
    "host": os.getenv("POSERING_HOST", "0.0.0.0"),
    "port": _env_int("POSERING_PORT", 5001),
}

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = "posering-secret-2026"
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

# Instantiate engine
engine = GameEngine(CONFIG)

AUDIO_SETTINGS = {
    "music_volume": 0.22,
    "effects_volume": 0.85,
    "music_enabled": True,
    "effects_enabled": True,
}

PREPARED_GAME = {
    "mode": None,
    "type": None,
    "players": [],
    "first_player": None,
    "player_colors": {},
    "status": "idle",
}

POSES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "poses.json")
COLOR_ORDER = ["RED", "YELLOW", "BLUE", "GREEN"]
VS_POSES_PER_TURN = 5
VS_SETUP_SECONDS = 10

VS_SESSION = {
    "active": False,
    "phase": "idle",
    "players": [],
    "player_colors": {},
    "turn_index": 0,
    "current_index": 0,
    "turns": [],
    "message": "",
}


def configure_runtime_logging():
    """Keep terminal output focused on startup, game events, and real warnings."""
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("socketio").setLevel(logging.WARNING)
    logging.getLogger("engineio").setLevel(logging.WARNING)
    app.logger.setLevel(logging.WARNING)


def _load_poses():
    if not os.path.exists(POSES_FILE):
        return []
    try:
        with open(POSES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_poses(poses):
    with open(POSES_FILE, "w", encoding="utf-8") as f:
        json.dump(poses, f, indent=2, ensure_ascii=False)


def _find_pose(pose_id):
    for pose in _load_poses():
        if pose.get("id") == pose_id:
            return pose
    return None


def _front_camera_b64():
    jpeg = engine.get_frame(0)
    if not jpeg:
        return None
    import base64
    return base64.b64encode(jpeg).decode("ascii")


def _snapshot_has_all_colors(snapshot):
    sets = (snapshot or {}).get("sets") or {}
    if not sets:
        return False
    for color in COLOR_ORDER:
        found = False
        for points in sets.values():
            if isinstance(points, dict) and points.get(color) is not None:
                found = True
                break
        if not found:
            return False
    return True


def _current_vs_players():
    players = VS_SESSION.get("players") or PREPARED_GAME.get("players") or ["Player 1", "Player 2"]
    if len(players) < 2:
        players = (players + ["Player 2"])[:2]
    return players[:2]


def _vs_turn_context():
    players = _current_vs_players()
    turn_index = int(VS_SESSION.get("turn_index", 0)) % 2
    creator = players[turn_index]
    challenger = players[1 - turn_index]
    return players, creator, challenger


def _public_vs_state(extra=None):
    players, creator, challenger = _vs_turn_context()
    state = {
        "active": VS_SESSION.get("active", False),
        "phase": VS_SESSION.get("phase", "idle"),
        "players": players,
        "player_colors": VS_SESSION.get("player_colors", {}),
        "turn_index": VS_SESSION.get("turn_index", 0),
        "current_index": VS_SESSION.get("current_index", 0),
        "poses_per_turn": VS_POSES_PER_TURN,
        "setup_seconds": VS_SETUP_SECONDS,
        "creator": creator,
        "challenger": challenger,
        "turns": VS_SESSION.get("turns", []),
        "message": VS_SESSION.get("message", ""),
    }
    if extra:
        state.update(extra)
    return state


def _emit_vs(extra=None):
    socketio.emit("vs_state", _public_vs_state(extra))


def _start_vs_setup(turn_index=None):
    if turn_index is not None:
        VS_SESSION["turn_index"] = int(turn_index)
    players, creator, challenger = _vs_turn_context()
    while len(VS_SESSION["turns"]) <= VS_SESSION["turn_index"]:
        VS_SESSION["turns"].append({
            "creator": creator,
            "challenger": challenger,
            "setup": [],
            "challenge": [],
            "total_time": None,
        })
    turn = VS_SESSION["turns"][VS_SESSION["turn_index"]]
    turn.update({"creator": creator, "challenger": challenger, "setup": [], "challenge": [], "total_time": None})
    VS_SESSION.update({
        "active": True,
        "phase": "setup",
        "current_index": 0,
        "message": f"{creator} sets poses. {challenger} hides.",
    })
    _emit_vs()


def _start_vs_challenge():
    players, creator, challenger = _vs_turn_context()
    turn = VS_SESSION["turns"][VS_SESSION["turn_index"]]
    if len(turn.get("setup", [])) < VS_POSES_PER_TURN:
        VS_SESSION["message"] = "Set all poses before starting the challenge."
        _emit_vs({"error": VS_SESSION["message"]})
        return

    VS_SESSION.update({
        "phase": "challenge_ready",
        "current_index": 0,
        "message": f"{challenger} get ready. Time starts after countdown.",
    })
    _emit_vs()


def _begin_vs_challenge_after_ready():
    players, creator, challenger = _vs_turn_context()
    turn = VS_SESSION["turns"][VS_SESSION["turn_index"]]
    VS_SESSION.update({
        "phase": "challenge",
        "current_index": 0,
        "message": f"{challenger} challenge. Time is being measured.",
        "challenge_started_at": time.time(),
        "lap_started_at": time.time(),
    })
    first_pose = turn["setup"][0]["pose"]
    engine.send_command("load_pose", first_pose)
    engine.send_command("start_game", _vs_engine_settings([challenger]))
    _emit_vs()


def _vs_engine_settings(players):
    return {
        "players": players,
        "player_colors": VS_SESSION.get("player_colors", {}),
        "difficulty": "medium",
        "poses_per_round": VS_POSES_PER_TURN,
        "num_rounds": 1,
        "simulation": CONFIG["simulation"],
        "a_cam0_index": CONFIG["a_cam0_index"],
        "a_cam1_index": CONFIG["a_cam1_index"],
        "a_backend": CONFIG["a_backend"],
        "a_calib_file": CONFIG["a_calib_file"],
        "use_b_set": CONFIG["use_b_set"],
        "use_remote_b_set": CONFIG["use_remote_b_set"],
        "b_cam0_index": CONFIG["b_cam0_index"],
        "b_cam1_index": CONFIG["b_cam1_index"],
        "b_backend": CONFIG["b_backend"],
        "b_calib_file": CONFIG["b_calib_file"],
        "remote_b_udp_ip": CONFIG["remote_b_udp_ip"],
        "remote_b_udp_port": CONFIG["remote_b_udp_port"],
        "ble_enabled": CONFIG["ble_enabled"],
        "ble_device_name": CONFIG["ble_device_name"],
        "ble_char_uuid": CONFIG["ble_char_uuid"],
        "feedback_target_color": CONFIG["feedback_target_color"],
        "vs_no_timeout": True,
    }


def _record_vs_challenge_clear(snap):
    turn_index = VS_SESSION.get("turn_index", 0)
    if turn_index >= len(VS_SESSION.get("turns", [])):
        return
    turn = VS_SESSION["turns"][turn_index]
    idx = int(VS_SESSION.get("current_index", 0))
    now = time.time()
    lap = max(0.0, now - float(VS_SESSION.get("lap_started_at", now)))
    turn.setdefault("challenge", []).append({
        "index": idx,
        "photo": snap.get("cam0") or _front_camera_b64(),
        "lap_time": lap,
        "cleared_at": now,
    })
    VS_SESSION["current_index"] = idx + 1

    if VS_SESSION["current_index"] >= VS_POSES_PER_TURN:
        turn["total_time"] = max(0.0, now - float(VS_SESSION.get("challenge_started_at", now)))
        if VS_SESSION.get("turn_index", 0) == 0:
            VS_SESSION.update({
                "phase": "turn_complete",
                "message": "First VS turn complete. Press START for the second setup.",
                "turn_index": 1,
                "current_index": 0,
            })
        else:
            VS_SESSION.update({
                "phase": "results",
                "message": "VS results ready.",
                "current_index": 0,
            })
        engine.send_command("reset")
        _emit_vs()
        return

    next_pose = turn["setup"][VS_SESSION["current_index"]]["pose"]
    VS_SESSION["lap_started_at"] = time.time()
    engine.send_command("next_pose")
    engine.send_command("load_pose", next_pose)
    engine.send_command("start_game", _vs_engine_settings([turn["challenger"]]))
    _emit_vs()

# ---------------------------------------------------------------------------
# Background broadcaster — pushes state to all clients at ~20 Hz
# ---------------------------------------------------------------------------

def broadcaster():
    """Runs in a daemon thread; emits game_state events to all SocketIO clients."""
    while True:
        state = engine.get_state()

        # game_state is already a plain string value (set by _publish_state)

        # One-shot snapshot event (sent once when a pose ends)
        snap = engine.pop_snapshot_event()
        if snap:
            if (
                VS_SESSION.get("active")
                and VS_SESSION.get("phase") == "challenge"
                and snap.get("result") == "cleared"
            ):
                _record_vs_challenge_clear(snap)
            socketio.emit("snapshot_event", snap)

        socketio.emit("game_state", state)

        time.sleep(0.05)   # 20 Hz


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets"),
        filename,
    )


@app.route("/player")
def player():
    return render_template("player.html")


@app.route("/operator")
def operator():
    return render_template(
        "operator.html",
        difficulties=list(DIFFICULTIES.keys()),
    )


# ---------------------------------------------------------------------------
# MJPEG video streams (operator screen)
# ---------------------------------------------------------------------------

def _gen_frames(cam_id: int):
    """Generator for MJPEG stream of the given camera."""
    placeholder = None   # lazy-create a blank frame if no feed available

    while True:
        jpeg = engine.get_frame(cam_id)

        if jpeg is None:
            # Generate a dark placeholder with text
            if placeholder is None:
                import numpy as np
                ph = 480; pw = 640
                img = (20 * __import__("numpy").ones((ph, pw, 3), dtype="uint8"))
                cv2.putText(img, f"Camera {cam_id}", (pw//2 - 80, ph//2 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 80, 80), 2)
                cv2.putText(img, "No signal", (pw//2 - 55, ph//2 + 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 60), 1)
                _, buf = cv2.imencode(".jpg", img)
                placeholder = buf.tobytes()
            jpeg = placeholder

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + jpeg +
            b"\r\n"
        )
        time.sleep(0.033)   # ~30 fps cap


@app.route("/video_feed/<int:cam_id>")
def video_feed(cam_id: int):
    if cam_id not in (0, 1, 2, 3):
        return "Invalid camera", 400
    return Response(
        _gen_frames(cam_id),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# REST endpoints (quick reads)
# ---------------------------------------------------------------------------

@app.route("/api/state")
def api_state():
    state = engine.get_state()
    # game_state is already a plain string value from _publish_state
    return jsonify(state)


@app.route("/api/ble_status")
def api_ble_status():
    return jsonify(engine.get_ble_status())


@app.route("/api/poses", methods=["GET"])
def api_poses():
    return jsonify(_load_poses())


@app.route("/api/poses", methods=["POST"])
def api_save_pose():
    payload = request.get_json(force=True) or {}
    name = str(payload.get("name", "")).strip()
    difficulty = str(payload.get("difficulty", "medium")).strip().lower()
    if difficulty == "high":
        difficulty = "hard"

    if not name:
        return jsonify({"error": "Pose name is required"}), 400
    if difficulty not in DIFFICULTIES:
        return jsonify({"error": "Difficulty must be easy, medium, or hard"}), 400

    snapshot = engine.get_current_pose_snapshot()
    if not snapshot or not snapshot.get("sets"):
        return jsonify({"error": "No live pose coordinates are available yet"}), 409

    pose = {
        "id": uuid.uuid4().hex,
        "name": name,
        "difficulty": difficulty,
        "created_at": time.time(),
        "sets": snapshot["sets"],
        "source": snapshot.get("source", "live"),
    }
    poses = _load_poses()
    poses.append(pose)
    _save_poses(poses)
    socketio.emit("pose_library", poses)
    return jsonify(pose), 201


@app.route("/api/poses/<pose_id>", methods=["DELETE"])
def api_delete_pose(pose_id):
    poses = _load_poses()
    next_poses = [pose for pose in poses if pose.get("id") != pose_id]
    if len(next_poses) == len(poses):
        return jsonify({"error": "Pose not found"}), 404
    _save_poses(next_poses)
    socketio.emit("pose_library", next_poses)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Socket.IO — operator commands
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    state = engine.get_state()
    emit("game_state", state)
    emit("audio_settings", AUDIO_SETTINGS)
    emit("pose_library", _load_poses())
    emit("lobby_setup", PREPARED_GAME)
    emit("vs_state", _public_vs_state())


@socketio.on("cmd_prepare_game")
def on_prepare_game(data):
    players = [str(p).strip() for p in (data or {}).get("players", []) if str(p).strip()]
    if not players:
        players = ["Player 1", "Player 2"]

    first_player = (data or {}).get("first_player")
    if first_player not in players:
        first_player = players[0]

    PREPARED_GAME.update({
        "mode": (data or {}).get("mode", "multiplayer"),
        "type": (data or {}).get("type", "coop"),
        "players": players,
        "first_player": first_player,
        "player_colors": (data or {}).get("player_colors", {}),
        "status": "ready_for_operator",
    })
    socketio.emit("lobby_setup", PREPARED_GAME)


@socketio.on("cmd_start_game")
def on_start_game(data):
    """
    data: {players, difficulty, poses_per_round, num_rounds}
    """
    data = data or {}
    if PREPARED_GAME.get("type") == "versus":
        if not VS_SESSION.get("active") or VS_SESSION.get("phase") in {"idle"}:
            VS_SESSION.update({
                "players": PREPARED_GAME.get("players", ["Player 1", "Player 2"]),
                "player_colors": PREPARED_GAME.get("player_colors", {}),
                "turn_index": 0,
                "turns": [],
            })
            _start_vs_setup(0)
            return
        if VS_SESSION.get("phase") == "setup_complete":
            _start_vs_challenge()
            return
        if VS_SESSION.get("phase") == "turn_complete":
            _start_vs_setup(VS_SESSION.get("turn_index", 1))
            return

    players = [p.strip() for p in data.get("players", PREPARED_GAME.get("players") or ["Player 1"]) if p.strip()]
    if not players:
        players = PREPARED_GAME.get("players") or ["Player 1"]

    settings = {
        "players":         players,
        "player_colors":   PREPARED_GAME.get("player_colors", {}),
        "difficulty":      data.get("difficulty", "medium"),
        "poses_per_round": int(data.get("poses_per_round", 5)),
        "num_rounds":      int(data.get("num_rounds", 3)),
        "simulation":      CONFIG["simulation"],
        "a_cam0_index":    CONFIG["a_cam0_index"],
        "a_cam1_index":    CONFIG["a_cam1_index"],
        "a_backend":       CONFIG["a_backend"],
        "a_calib_file":    data.get("a_calib_file", CONFIG["a_calib_file"]),
        "use_b_set":       CONFIG["use_b_set"],
        "use_remote_b_set": CONFIG["use_remote_b_set"],
        "b_cam0_index":    CONFIG["b_cam0_index"],
        "b_cam1_index":    CONFIG["b_cam1_index"],
        "b_backend":       CONFIG["b_backend"],
        "b_calib_file":    data.get("b_calib_file", CONFIG["b_calib_file"]),
        "remote_b_udp_ip": CONFIG["remote_b_udp_ip"],
        "remote_b_udp_port": CONFIG["remote_b_udp_port"],
        "ble_enabled":     CONFIG["ble_enabled"],
        "ble_device_name": CONFIG["ble_device_name"],
        "ble_char_uuid":   CONFIG["ble_char_uuid"],
        "feedback_target_color": CONFIG["feedback_target_color"],
    }
    engine.send_command("start_game", settings)
    PREPARED_GAME.update({
        "players": players,
        "status": "started",
    })
    socketio.emit("lobby_setup", PREPARED_GAME)
    print(f"[Server] start_game: {settings}")


@socketio.on("cmd_set_origin")
def on_set_origin():
    engine.send_command("set_origin")


@socketio.on("cmd_set_targets")
def on_set_targets():
    engine.send_command("set_targets")


@socketio.on("cmd_reset")
def on_reset():
    VS_SESSION.update({
        "active": False,
        "phase": "idle",
        "players": [],
        "player_colors": {},
        "turn_index": 0,
        "current_index": 0,
        "turns": [],
        "message": "",
    })
    PREPARED_GAME.update({
        "mode": None,
        "type": None,
        "players": [],
        "first_player": None,
        "player_colors": {},
        "status": "idle",
    })
    socketio.emit("lobby_setup", PREPARED_GAME)
    _emit_vs()
    engine.send_command("reset")


@socketio.on("cmd_vs_capture_setup_pose")
def on_vs_capture_setup_pose():
    if not VS_SESSION.get("active") or VS_SESSION.get("phase") != "setup":
        return
    turn_index = VS_SESSION.get("turn_index", 0)
    if turn_index >= len(VS_SESSION.get("turns", [])):
        return
    snapshot = engine.get_current_pose_snapshot()
    if not _snapshot_has_all_colors(snapshot):
        VS_SESSION["message"] = "Cannot save pose: all colors must be visible."
        _emit_vs({"error": VS_SESSION["message"], "capture_ok": False})
        return
    idx = int(VS_SESSION.get("current_index", 0))
    pose = {
        "id": f"vs-{uuid.uuid4().hex}",
        "name": f"VS Pose {idx + 1}",
        "difficulty": "medium",
        "created_at": time.time(),
        "sets": snapshot["sets"],
        "source": snapshot.get("source", "live"),
    }
    VS_SESSION["turns"][turn_index].setdefault("setup", []).append({
        "index": idx,
        "pose": pose,
        "photo": _front_camera_b64(),
        "saved_at": time.time(),
    })
    VS_SESSION["current_index"] = idx + 1
    if VS_SESSION["current_index"] >= VS_POSES_PER_TURN:
        VS_SESSION.update({
            "phase": "setup_complete",
            "message": "All setup poses saved. Press START when the challenger is ready.",
        })
    else:
        VS_SESSION["message"] = f"Pose {idx + 1} saved."
    _emit_vs({"capture_ok": True})


@socketio.on("cmd_vs_begin_challenge_after_ready")
def on_vs_begin_challenge_after_ready():
    if not VS_SESSION.get("active") or VS_SESSION.get("phase") != "challenge_ready":
        return
    _begin_vs_challenge_after_ready()


@socketio.on("cmd_next_pose")
def on_next_pose():
    """Player or operator taps NEXT after seeing snapshot."""
    engine.send_command("next_pose")


@socketio.on("cmd_load_pose")
def on_load_pose(data):
    pose_id = (data or {}).get("id")
    pose = _find_pose(pose_id)
    if not pose:
        emit("pose_error", {"error": "Pose not found"})
        return
    engine.send_command("load_pose", pose)
    socketio.emit("pose_selected", {
        "id": pose["id"],
        "name": pose["name"],
        "difficulty": pose.get("difficulty", "medium"),
    })


@socketio.on("cmd_audio_settings")
def on_audio_settings(data):
    def clamp01(value, default):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return default

    AUDIO_SETTINGS["music_volume"] = clamp01(
        data.get("music_volume"), AUDIO_SETTINGS["music_volume"]
    )
    AUDIO_SETTINGS["effects_volume"] = clamp01(
        data.get("effects_volume"), AUDIO_SETTINGS["effects_volume"]
    )
    AUDIO_SETTINGS["music_enabled"] = bool(data.get("music_enabled", True))
    AUDIO_SETTINGS["effects_enabled"] = bool(data.get("effects_enabled", True))
    socketio.emit("audio_settings", AUDIO_SETTINGS)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    configure_runtime_logging()

    # Start game engine
    engine.start()
    print(f"[Server] Game engine started (simulation={CONFIG['simulation']})")

    if CONFIG["ble_enabled"]:
        print(f"[Server] BLE enabled for {CONFIG['ble_device_name']}")
    else:
        print("[Server] BLE disabled")

    # Start broadcaster thread
    import threading
    t = threading.Thread(target=broadcaster, daemon=True)
    t.start()
    print("[Server] Socket.IO broadcaster working")

    print(f"\n{'='*50}")
    print(f"  PoseRing Web Server")
    print(f"  http://localhost:{CONFIG['port']}")
    print(f"  Player  → http://localhost:{CONFIG['port']}/player")
    print(f"  Operator→ http://localhost:{CONFIG['port']}/operator")
    print(f"  Mode    : {'SIMULATION' if CONFIG['simulation'] else 'LIVE'}")
    print(f"{'='*50}\n")

    socketio.run(
        app,
        host=CONFIG["host"],
        port=CONFIG["port"],
        debug=False,
        allow_unsafe_werkzeug=True,
    )
