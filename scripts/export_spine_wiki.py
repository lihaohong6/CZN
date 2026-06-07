#!/usr/bin/env python3
"""Experimental Spine animation exporter for wiki format comparisons.

The script renders selected Spine 3.8 combatant assets in headless Chrome,
encodes deterministic WebM output from captured frames, and never overwrites
existing exports.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import http.server
import json
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_ROOT = REPO_ROOT / "vendor" / "assets"
L2D_ROOT = REPO_ROOT / "vendor" / "l2d"
DB_CHAR_BASE = ASSETS_ROOT / "db" / "char_base@char_base.json"
TEXT_EN = ASSETS_ROOT / "text" / "en" / "text.json"
MODEL_DIR = ASSETS_ROOT / "model"
CARD_DIR = ASSETS_ROOT / "card"

DEFAULT_RUNTIME_URLS = [
    "https://unpkg.com/@esotericsoftware/spine-player@3.8.*/dist/iife/spine-player.js",
    "https://cdn.jsdelivr.net/gh/EsotericSoftware/spine-runtimes@3.8/spine-ts/build/spine-player.js",
]

MODEL_EXPORTS = [
    ("death", ("death_ready", "death")),
    ("idle", ("idle",)),
    ("move", ("move",)),
    ("victory", ("victory_ready", "victory")),
    ("collapse_idle", ("collapse_idle",)),
    ("enter", ("enter_play", "enter_end")),
]


@dataclasses.dataclass(frozen=True)
class Character:
    id: int
    name: str
    slug: str


@dataclasses.dataclass
class ExportJob:
    group: str
    character: Character
    source_json: Path
    source_atlas: Path
    output_dir: Path
    output_stem: str
    animations: tuple[str, ...]
    intrinsic_width: float
    intrinsic_height: float
    final_width: int
    final_height: int
    capture_width: int
    capture_height: int
    duration_seconds: float

    @property
    def key(self) -> str:
        return f"{self.group}/{self.character.id}/{self.output_stem}"


@dataclasses.dataclass(frozen=True)
class VideoCrop:
    x: int
    y: int
    width: int
    height: int
    source_width: int
    source_height: int


class ExportResultHandler(http.server.SimpleHTTPRequestHandler):
    """Serves repo files and receives deterministic export frames."""

    server: "ExportServer"

    def log_message(self, _format: str, *_args: Any) -> None:
        if self.server.verbose:
            super().log_message(_format, *_args)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        job_id = params.get("id", [""])[0]
        length = int(self.headers.get("Content-Length", "0"))

        if parsed.path == "/__spine_export__/frame":
            frame_dir = self.server.frame_dirs.get(job_id)
            if frame_dir is None:
                self.send_error(404, "unknown export job")
                return
            try:
                frame_index = int(params.get("frame", [""])[0])
            except ValueError:
                self.send_error(400, "missing frame index")
                return
            if frame_index < 0:
                self.send_error(400, "invalid frame index")
                return
            target = frame_dir / f"frame_{frame_index:06d}.png"
            with target.open("wb") as f:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            self._send_json({"ok": True})
            return

        if parsed.path == "/__spine_export__/complete":
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {"message": body}
            payload["id"] = job_id
            payload["ok"] = True
            payload["frames_complete"] = True
            self.server.results.put(payload)
            self._send_json({"ok": True})
            return

        if parsed.path == "/__spine_export__/capture":
            target = self.server.capture_paths.get(job_id)
            if target is None:
                self.send_error(404, "unknown export job")
                return
            with target.open("wb") as f:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            self.server.results.put({"id": job_id, "ok": True, "capture": str(target)})
            self._send_json({"ok": True})
            return

        if parsed.path == "/__spine_export__/error":
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"message": body}
            payload["id"] = job_id
            payload["ok"] = False
            self.server.results.put(payload)
            self._send_json({"ok": True})
            return

        self.send_error(404, "unknown export endpoint")

    def _send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ExportServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[ExportResultHandler], directory: Path, verbose: bool) -> None:
        super().__init__(address, lambda *args, **kwargs: handler(*args, directory=str(directory), **kwargs))
        self.capture_paths: dict[str, Path] = {}
        self.frame_dirs: dict[str, Path] = {}
        self.results: queue.Queue[dict[str, Any]] = queue.Queue()
        self.verbose = verbose

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--character", action="append", help="Playable character ID or slug/name. May be passed more than once.")
    parser.add_argument("--type", default="all", help="Comma-separated export groups: all, battle_ready, model, card.")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--output-scale", type=float, default=4.0, help="Scale intrinsic skeleton bounds to output dimensions.")
    parser.add_argument("--battle-resolution-scale", type=float, default=2.0 / 3.0, help="Additional output-size multiplier for battle_ready exports only.")
    parser.add_argument("--card-output-scale", type=float, default=12.0, help="Scale card skeleton bounds before cropping black borders.")
    parser.add_argument("--render-scale", choices=("1", "2", "3", "4"), default="2", help="Browser backing-canvas scale before ffmpeg downsampling.")
    parser.add_argument("--max-capture-edge", type=int, default=0, help="Optional maximum browser backing-canvas edge. Large exports automatically lower render scale to fit.")
    parser.add_argument("--max-capture-pixels", type=int, default=24_000_000, help="Maximum browser backing-canvas pixels before automatically lowering render scale.")
    parser.add_argument("--large-capture-pixels", type=int, default=20_000_000, help="Browser backing-canvas pixels before applying large-capture FPS throttling.")
    parser.add_argument("--large-capture-fps", type=int, default=12, help="FPS to use when a large deterministic capture is automatically downscaled.")
    parser.add_argument("--min-large-capture-fps", type=int, default=6, help="Lowest FPS allowed for automatic large deterministic capture throttling.")
    parser.add_argument("--max-deterministic-megapixel-frames", type=float, default=1200.0, help="Maximum megapixel-frames for automatically downscaled deterministic captures.")
    parser.add_argument("--vp9-crf", type=int, default=18, help="VP9 CRF for deterministic and crop transcodes. Lower is higher quality.")
    parser.add_argument("--vp9-cpu-used", type=int, default=4, help="libvpx-vp9 speed setting. Higher is faster, usually larger/slightly lower quality.")
    parser.add_argument("--vp9-deadline", choices=("best", "good", "realtime"), default="good", help="libvpx-vp9 encoding deadline.")
    parser.add_argument("--ffmpeg-threads", type=int, default=0, help="ffmpeg encoder thread count. 0 lets ffmpeg choose.")
    parser.add_argument("--padding", type=float, default=24.0, help="Padding in skeleton coordinate units before output scaling.")
    parser.add_argument("--battle-crop-padding", type=int, default=16, help="Pixel padding to keep around detected battle_ready content after cropping.")
    parser.add_argument("--card-crop-padding", type=int, default=24, help="Pixel padding to keep around detected card content after cropping.")
    parser.add_argument("--battle-transparent", action="store_true", help="Keep battle_ready exports transparent. By default they use the preview's dark background to avoid additive-effect alpha artifacts.")
    parser.add_argument("--opaque-crop-threshold", type=int, default=8, help="RGB distance from the preview background required for opaque crop detection.")
    parser.add_argument("--no-battle-crop", action="store_true", help="Disable post-capture black border cropping for battle_ready exports.")
    parser.add_argument("--no-card-crop", action="store_true", help="Disable post-capture black border cropping for card exports.")
    parser.add_argument("--max-edge", type=int, default=0, help="Optional maximum output width/height.")
    parser.add_argument("--card-max-edge", type=int, default=4096, help="Optional maximum card capture width/height before cropping.")
    parser.add_argument("--min-duration", type=float, default=1.0)
    parser.add_argument("--duration-pad", type=float, default=0.25)
    parser.add_argument("--capture-timeout", type=float, default=360.0)
    parser.add_argument("--capture-mode", choices=("auto", "realtime", "deterministic"), default="deterministic", help="Use fast MediaRecorder capture, fixed frame capture, or auto mode.")
    parser.add_argument("--deterministic-fallback", action="store_true", help="In auto mode, retry with fixed PNG frames if realtime capture duration drifts.")
    parser.add_argument("--duration-tolerance", type=float, default=0.35, help="Allowed WebM duration drift in seconds before auto mode falls back to deterministic capture.")
    parser.add_argument("--force-swiftshader", action="store_true", help="Force Chrome's software WebGL renderer. Off by default so hardware GPU can be used.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--spine-runtime-url", action="append", help="Spine Player JS URL or local path. May be passed more than once.")
    parser.add_argument("--chrome", default=shutil.which("google-chrome") or shutil.which("chromium") or "google-chrome")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing exported WebM files instead of skipping them.")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    groups = parse_groups(args.type)
    characters = filter_characters(load_playable_characters(), args.character)
    manifest: dict[str, Any] = {
        "settings": {
            "format": "webm",
            "groups": sorted(groups),
            "fps": args.fps,
            "output_scale": args.output_scale,
            "battle_resolution_scale": args.battle_resolution_scale,
            "card_output_scale": args.card_output_scale,
            "render_scale": render_scale(args),
            "max_capture_edge": args.max_capture_edge,
            "max_capture_pixels": args.max_capture_pixels,
            "large_capture_pixels": args.large_capture_pixels,
            "large_capture_fps": args.large_capture_fps,
            "min_large_capture_fps": args.min_large_capture_fps,
            "max_deterministic_megapixel_frames": args.max_deterministic_megapixel_frames,
            "vp9_crf": args.vp9_crf,
            "vp9_cpu_used": args.vp9_cpu_used,
            "vp9_deadline": args.vp9_deadline,
            "ffmpeg_threads": args.ffmpeg_threads,
            "padding": args.padding,
            "battle_transparent": args.battle_transparent,
            "opaque_crop_threshold": args.opaque_crop_threshold,
            "battle_crop": not args.no_battle_crop,
            "battle_crop_padding": args.battle_crop_padding,
            "card_crop": not args.no_card_crop,
            "card_crop_padding": args.card_crop_padding,
            "max_edge": args.max_edge,
            "card_max_edge": args.card_max_edge,
            "min_duration": args.min_duration,
            "duration_pad": args.duration_pad,
            "capture_mode": args.capture_mode,
            "deterministic_fallback": args.deterministic_fallback,
            "duration_tolerance": args.duration_tolerance,
            "force_swiftshader": args.force_swiftshader,
            "overwrite": args.overwrite,
        },
        "jobs": [],
        "skipped": [],
        "errors": [],
    }

    jobs, skipped = build_jobs(characters, groups, args)
    manifest["skipped"].extend(skipped)

    if args.dry_run:
        print_dry_run(jobs, skipped, args)
        return 0

    validate_tools(args, jobs)
    L2D_ROOT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="spine-wiki-export-") as tmp:
        tmp_dir = Path(tmp)
        with run_export_server(args.verbose) as server:
            base_url = f"http://127.0.0.1:{server.server_port}"
            for index, job in enumerate(jobs, start=1):
                print(f"[{index}/{len(jobs)}] {job.key}", flush=True)
                result = export_job(job, args, server, base_url, tmp_dir)
                if result.get("ok"):
                    manifest["jobs"].append(result)
                elif result.get("skipped"):
                    manifest["skipped"].append(result)
                else:
                    manifest["errors"].append(result)

        if args.keep_temp:
            kept = L2D_ROOT / f"export_temp_{int(time.time())}"
            shutil.copytree(tmp_dir, kept, ignore=ignore_export_temp)
            manifest["kept_temp_dir"] = str(kept.relative_to(REPO_ROOT))

    write_manifest(manifest)
    print_summary(manifest)
    return 1 if manifest["errors"] else 0


def parse_groups(raw: str) -> set[str]:
    groups = {part.strip().lower() for part in raw.split(",") if part.strip()}
    if not groups or "all" in groups:
        return {"battle_ready", "model", "card"}
    invalid = groups - {"battle_ready", "model", "card"}
    if invalid:
        raise SystemExit(f"Unsupported type(s): {', '.join(sorted(invalid))}")
    return groups


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_text_map() -> dict[str, str]:
    entries = load_json(TEXT_EN)
    return {entry["id"]: entry["text"] for entry in entries}


def load_playable_characters() -> list[Character]:
    text = load_text_map()
    chars = []
    for entry in load_json(DB_CHAR_BASE):
        if entry.get("char_use_playable") != "YES":
            continue
        char_id = int(entry["id"])
        name = text.get(f"char_base@name@{char_id}", str(char_id))
        chars.append(Character(id=char_id, name=name, slug=slugify(name) or str(char_id)))
    return sorted(chars, key=lambda item: item.id)


def filter_characters(characters: list[Character], filters: list[str] | None) -> list[Character]:
    if not filters:
        return characters
    selected: list[Character] = []
    by_id = {str(char.id): char for char in characters}
    by_slug = {char.slug: char for char in characters}
    by_name = {char.name.lower(): char for char in characters}
    for raw in filters:
        key = raw.strip().lower()
        char = by_id.get(key) or by_slug.get(slugify(key)) or by_name.get(key)
        if char is None:
            raise SystemExit(f"Unknown playable character: {raw}")
        if char not in selected:
            selected.append(char)
    return selected


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return value


def build_jobs(characters: list[Character], groups: set[str], args: argparse.Namespace) -> tuple[list[ExportJob], list[dict[str, Any]]]:
    jobs: list[ExportJob] = []
    skipped: list[dict[str, Any]] = []
    for char in characters:
        if "battle_ready" in groups:
            add_job(
                jobs,
                skipped,
                char,
                "battle_ready",
                MODEL_DIR / f"{char.id}_battle_ready.json",
                "b_idle",
                ("b_idle",),
                args,
            )
        if "model" in groups:
            for stem, animations in MODEL_EXPORTS:
                add_job(
                    jobs,
                    skipped,
                    char,
                    "model",
                    MODEL_DIR / f"{char.id}.json",
                    stem,
                    animations,
                    args,
                )
        if "card" in groups:
            for number in range(1, 6):
                source_json = CARD_DIR / f"unique_{char.id}_{number:02d}.json"
                source_atlas = source_json.with_suffix(".atlas")
                if not source_json.exists() or not source_atlas.exists():
                    skipped.append(skip_payload(char, "card", source_json, "missing source json or atlas"))
                    continue
                data = load_json(source_json)
                animations = list(data.get("animations", {}))
                if not animations:
                    skipped.append(skip_payload(char, "card", source_json, "no animations"))
                    continue
                primary = "animation" if "animation" in animations else animations[0]
                ordered = [primary] + [name for name in animations if name != primary]
                for index, animation in enumerate(ordered):
                    stem = f"unique_{number:02d}" if index == 0 else f"unique_{number:02d}-{safe_stem(animation)}"
                    add_job(jobs, skipped, char, "card", source_json, stem, (animation,), args, data=data)
    return jobs, skipped


def add_job(
    jobs: list[ExportJob],
    skipped: list[dict[str, Any]],
    char: Character,
    group: str,
    source_json: Path,
    output_stem: str,
    animations: tuple[str, ...],
    args: argparse.Namespace,
    data: dict[str, Any] | None = None,
) -> None:
    source_atlas = source_json.with_suffix(".atlas")
    if not source_json.exists() or not source_atlas.exists():
        skipped.append(skip_payload(char, group, source_json, "missing source json or atlas"))
        return
    data = data or load_json(source_json)
    available = set(data.get("animations", {}))
    missing = [animation for animation in animations if animation not in available]
    if missing:
        skipped.append(skip_payload(char, group, source_json, "missing animation(s): " + ", ".join(missing)))
        return
    skeleton = data.get("skeleton", {})
    intrinsic_width = float(skeleton.get("width") or 0)
    intrinsic_height = float(skeleton.get("height") or 0)
    if intrinsic_width <= 0 or intrinsic_height <= 0:
        skipped.append(skip_payload(char, group, source_json, "missing intrinsic skeleton width/height"))
        return
    output_scale = group_output_scale(group, args)
    max_edge = args.card_max_edge if group == "card" else args.max_edge
    final_width, final_height = compute_dimensions(intrinsic_width, intrinsic_height, output_scale, args.padding, max_edge)
    capture_width = final_width
    capture_height = final_height
    duration = sum(animation_duration(data["animations"][animation]) for animation in animations)
    duration = max(args.min_duration, duration + args.duration_pad)
    jobs.append(
        ExportJob(
            group=group,
            character=char,
            source_json=source_json,
            source_atlas=source_atlas,
            output_dir=L2D_ROOT / group / f"{char.id}-{char.slug}",
            output_stem=safe_stem(output_stem),
            animations=animations,
            intrinsic_width=intrinsic_width,
            intrinsic_height=intrinsic_height,
            final_width=final_width,
            final_height=final_height,
            capture_width=capture_width,
            capture_height=capture_height,
            duration_seconds=duration,
        )
    )


def skip_payload(char: Character, group: str, source_json: Path, reason: str) -> dict[str, Any]:
    return {
        "character_id": char.id,
        "character": char.name,
        "group": group,
        "source": rel(source_json),
        "reason": reason,
    }


def compute_dimensions(width: float, height: float, output_scale: float, padding: float, max_edge: int) -> tuple[int, int]:
    padded_width = max(1.0, width + padding * 2.0)
    padded_height = max(1.0, height + padding * 2.0)
    final_width = padded_width * output_scale
    final_height = padded_height * output_scale
    if max_edge and max(final_width, final_height) > max_edge:
        scale = max_edge / max(final_width, final_height)
        final_width *= scale
        final_height *= scale
    return even_int(final_width), even_int(final_height)


def group_output_scale(group: str, args: argparse.Namespace) -> float:
    if group == "card":
        return args.card_output_scale
    if group == "battle_ready":
        return args.output_scale * args.battle_resolution_scale
    return args.output_scale


def even_int(value: float) -> int:
    number = max(2, int(math.ceil(value)))
    return number if number % 2 == 0 else number + 1


def safe_stem(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9_.+-]+", "-", value).strip("-")
    return value or "animation"


def animation_duration(animation: Any) -> float:
    return max(iter_times(animation), default=1.0)


def iter_times(value: Any) -> list[float]:
    times: list[float] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "time" and isinstance(item, (int, float)):
                times.append(float(item))
            else:
                times.extend(iter_times(item))
    elif isinstance(value, list):
        for item in value:
            times.extend(iter_times(item))
    return times


def print_dry_run(jobs: list[ExportJob], skipped: list[dict[str, Any]], args: argparse.Namespace) -> None:
    print(f"Planned jobs: {len(jobs)}")
    print("Format: webm")
    for job in jobs:
        scale = effective_render_scale(job, args)
        capture_fps = effective_capture_fps(job, args, scale)
        capture_width, capture_height = actual_capture_dimensions(job, scale)
        print(
            f"{job.key}: {rel(job.source_json)} "
            f"{'+'.join(job.animations)} "
            f"{job.final_width}x{job.final_height} "
            f"capture {capture_width}x{capture_height} "
            f"scale {scale}x "
            f"capture fps {capture_fps} "
            f"output fps {args.fps}"
        )
    if skipped:
        print(f"\nSkipped before export: {len(skipped)}")
        for item in skipped[:40]:
            print(f"- {item['group']} {item['character_id']} {item['source']}: {item['reason']}")
        if len(skipped) > 40:
            print(f"- ... {len(skipped) - 40} more")


def validate_tools(args: argparse.Namespace, jobs: list[ExportJob]) -> None:
    commands = [("Chrome", args.chrome)]
    if jobs:
        commands.append(("ffmpeg", "ffmpeg"))
        commands.append(("ffprobe", "ffprobe"))
    for label, command in commands:
        if not shutil.which(command) and not Path(command).exists():
            raise SystemExit(f"{label} executable not found: {command}")


@contextlib.contextmanager
def run_export_server(verbose: bool) -> Any:
    server = ExportServer(("127.0.0.1", find_free_port()), ExportResultHandler, REPO_ROOT, verbose)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ignore_export_temp(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name.startswith("chrome-")}


def export_job(
    job: ExportJob,
    args: argparse.Namespace,
    server: ExportServer,
    base_url: str,
    tmp_dir: Path,
) -> dict[str, Any]:
    target = job.output_dir / f"{job.output_stem}.webm"
    if target.exists() and not args.overwrite:
        return {
            "skipped": True,
            "key": job.key,
            "reason": "target already exists",
            "existing": [rel(target)],
        }

    job.output_dir.mkdir(parents=True, exist_ok=True)
    job_id = f"{int(time.time() * 1000)}-{os.getpid()}-{safe_stem(job.key)}"
    try:
        capture_path, capture_meta = capture_job_video(job_id, job, args, server, base_url, tmp_dir)

        crop = capture_meta.get("crop")
        source_for_final = capture_path
        scale = int(capture_meta.get("render_scale") or effective_render_scale(job, args))
        if capture_meta["mode"] != "deterministic":
            target_width = job.final_width
            target_height = job.final_height
            needs_transcode = scale != 1
            if should_crop_job(job, args):
                crop = detect_video_crop(capture_path, scaled_crop_padding(job, args, scale), job_uses_alpha(job, args))
                needs_transcode = needs_transcode or crop is not None
                if crop is not None:
                    target_width, target_height = scaled_crop_dimensions(crop, scale)
            if needs_transcode:
                normalized_path = tmp_dir / f"{job_id}.normalized.webm"
                transcode_video(capture_path, normalized_path, args, target_width, target_height, crop, job_uses_alpha(job, args))
                source_for_final = normalized_path

        output_width, output_height = video_dimensions(source_for_final)

        shutil.copyfile(source_for_final, target)
        return {
            "ok": True,
            "key": job.key,
            "character_id": job.character.id,
            "character": job.character.name,
            "group": job.group,
            "source_json": rel(job.source_json),
            "source_atlas": rel(job.source_atlas),
            "animations": list(job.animations),
            "intrinsic_dimensions": [job.intrinsic_width, job.intrinsic_height],
            "dimensions": [output_width, output_height],
            "planned_dimensions": [job.final_width, job.final_height],
            "capture_dimensions": capture_meta["capture_dimensions"],
            "requested_render_scale": render_scale(args),
            "render_scale": scale,
            "fps": capture_meta.get("output_fps", args.fps),
            "capture_fps": capture_meta.get("capture_fps", args.fps),
            "output_fps": capture_meta.get("output_fps", args.fps),
            "capture_mode": capture_meta["mode"],
            "actual_duration_seconds": capture_meta.get("actual_duration_seconds"),
            "frame_count": capture_meta.get("frame_count"),
            "crop": dataclasses.asdict(crop) if crop else None,
            "duration_seconds": round(job.duration_seconds, 4),
            "output": rel(target),
        }
    except Exception as exc:  # noqa: BLE001 - manifest should record all job failures.
        return error_payload(job, str(exc))


def capture_job_video(
    job_id: str,
    job: ExportJob,
    args: argparse.Namespace,
    server: ExportServer,
    base_url: str,
    tmp_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    modes = [args.capture_mode]
    if args.capture_mode == "auto":
        modes = ["realtime", "deterministic"] if args.deterministic_fallback else ["realtime"]

    errors: list[str] = []
    for mode in modes:
        capture_id = f"{job_id}-{mode}"
        try:
            if mode == "realtime":
                capture_path = capture_realtime_video(capture_id, job, args, server, base_url, tmp_dir)
                actual_duration = video_duration(capture_path)
                if abs(actual_duration - job.duration_seconds) > args.duration_tolerance:
                    message = (
                        f"realtime duration drifted to {actual_duration:.3f}s; "
                        f"expected {job.duration_seconds:.3f}s"
                    )
                    if args.capture_mode == "auto":
                        errors.append(message)
                        continue
                    raise RuntimeError(message)
                return capture_path, {
                    "mode": mode,
                    "actual_duration_seconds": round(actual_duration, 4),
                    "frame_count": None,
                    "capture_dimensions": list(actual_capture_dimensions(job, effective_render_scale(job, args))),
                    "render_scale": effective_render_scale(job, args),
                    "capture_fps": effective_capture_fps(job, args, effective_render_scale(job, args)),
                    "output_fps": args.fps,
                    "crop": None,
                }

            if mode == "deterministic":
                capture_path, frame_count, crop = capture_deterministic_video(capture_id, job, args, server, base_url, tmp_dir)
                actual_duration = video_duration(capture_path)
                return capture_path, {
                    "mode": mode,
                    "actual_duration_seconds": round(actual_duration, 4),
                    "frame_count": frame_count,
                    "fallback_reason": errors[-1] if errors else None,
                    "capture_dimensions": list(actual_capture_dimensions(job, effective_render_scale(job, args))),
                    "render_scale": effective_render_scale(job, args),
                    "capture_fps": effective_capture_fps(job, args, effective_render_scale(job, args)),
                    "output_fps": args.fps,
                    "crop": crop,
                }

            raise RuntimeError(f"unsupported capture mode: {mode}")
        except Exception as exc:  # noqa: BLE001 - try the configured fallback.
            if args.capture_mode != "auto" or mode == modes[-1]:
                raise
            errors.append(str(exc))

    raise RuntimeError("; ".join(errors) or "capture failed")


def capture_realtime_video(
    capture_id: str,
    job: ExportJob,
    args: argparse.Namespace,
    server: ExportServer,
    base_url: str,
    tmp_dir: Path,
) -> Path:
    capture_path = tmp_dir / f"{capture_id}.realtime.webm"
    server.capture_paths[capture_id] = capture_path
    chrome = None
    try:
        scale = str(effective_render_scale(job, args))
        fps = effective_capture_fps(job, args, int(scale))
        url = build_preview_export_url(base_url, capture_id, job, args, runtime_urls(args), fps, "realtime", scale)
        chrome = launch_chrome(args, url, tmp_dir / f"chrome-{capture_id}")
        capture_result = wait_for_capture(server, capture_id, args.capture_timeout)
        if not capture_result.get("ok"):
            raise RuntimeError(capture_result.get("message", "browser capture failed"))
        if not capture_path.exists() or capture_path.stat().st_size == 0:
            raise RuntimeError("browser realtime capture was empty")
        return capture_path
    finally:
        if chrome is not None:
            terminate_process(chrome)
        server.capture_paths.pop(capture_id, None)


def capture_deterministic_video(
    capture_id: str,
    job: ExportJob,
    args: argparse.Namespace,
    server: ExportServer,
    base_url: str,
    tmp_dir: Path,
) -> tuple[Path, int, VideoCrop | None]:
    frame_dir = tmp_dir / f"{capture_id}-frames"
    frame_dir.mkdir(parents=True)
    capture_path = tmp_dir / f"{capture_id}.deterministic.webm"
    server.frame_dirs[capture_id] = frame_dir
    chrome = None
    try:
        scale = effective_render_scale(job, args)
        fps = effective_capture_fps(job, args, scale)
        url = build_preview_export_url(base_url, capture_id, job, args, runtime_urls(args), fps, "deterministic", str(scale))
        chrome = launch_chrome(args, url, tmp_dir / f"chrome-{capture_id}")
        capture_result = wait_for_capture(server, capture_id, args.capture_timeout)
        if not capture_result.get("ok"):
            raise RuntimeError(capture_result.get("message", "browser capture failed"))
        frame_count = int(capture_result.get("frames") or 0)
        if frame_count <= 0:
            raise RuntimeError("browser did not report exported frames")
        missing = missing_frames(frame_dir, frame_count)
        if missing:
            raise RuntimeError(f"browser export missed frame(s): {format_missing_frames(missing)}")
        crop = None
        target_width = job.final_width
        target_height = job.final_height
        if should_crop_job(job, args):
            crop = detect_frame_crop(
                frame_dir,
                frame_count,
                scaled_crop_padding(job, args, scale),
                job_uses_alpha(job, args),
                args.opaque_crop_threshold,
            )
            if crop is not None:
                target_width, target_height = scaled_crop_dimensions(crop, scale)
        encode_frames(frame_dir, capture_path, args, target_width, target_height, crop, fps, args.fps, job_uses_alpha(job, args))
        return capture_path, frame_count, crop
    finally:
        if chrome is not None:
            terminate_process(chrome)
        server.frame_dirs.pop(capture_id, None)


def runtime_urls(args: argparse.Namespace) -> list[str]:
    if not args.spine_runtime_url:
        return DEFAULT_RUNTIME_URLS
    urls = []
    for value in args.spine_runtime_url:
        path = Path(value)
        if path.exists():
            urls.append(path.resolve().as_uri())
        else:
            urls.append(value)
    return urls


def build_preview_export_url(
    base_url: str,
    job_id: str,
    job: ExportJob,
    args: argparse.Namespace,
    runtime_url_list: list[str],
    fps: int,
    capture_mode: str,
    scale: str,
) -> str:
    params = {
        "export": "1",
        "exportId": job_id,
        "captureMode": capture_mode,
        "json": rel(job.source_json),
        "atlas": rel(job.source_atlas),
        "anim": job.animations[0] if job.animations else "",
        "animations": ",".join(job.animations),
        "width": str(job.capture_width),
        "height": str(job.capture_height),
        "fps": str(fps),
        "duration": f"{job.duration_seconds:.4f}",
        "scale": scale,
        "transparent": "1" if job_uses_alpha(job, args) else "0",
        "runtime": "|".join(runtime_url_list),
    }
    return base_url + "/spine-preview.html?" + urllib.parse.urlencode(params)


def launch_chrome(args: argparse.Namespace, url: str, user_data_dir: Path) -> subprocess.Popen[bytes]:
    command = [
        args.chrome,
        "--headless=new",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        f"--user-data-dir={user_data_dir}",
        "--window-size=1280,960",
    ]
    if args.force_swiftshader:
        command.extend([
            "--enable-unsafe-swiftshader",
            "--use-gl=swiftshader",
            "--use-angle=swiftshader",
        ])
    command.append(url)
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def missing_frames(frame_dir: Path, frame_count: int) -> list[int]:
    return [index for index in range(frame_count) if not (frame_dir / f"frame_{index:06d}.png").exists()]


def format_missing_frames(frames: list[int]) -> str:
    if len(frames) <= 10:
        return ", ".join(str(frame) for frame in frames)
    return ", ".join(str(frame) for frame in frames[:10]) + f", ... {len(frames) - 10} more"


def render_scale(args: argparse.Namespace) -> int:
    return int(args.render_scale)


def effective_render_scale(job: ExportJob, args: argparse.Namespace) -> int:
    scale = render_scale(args)
    while scale > 1:
        width, height = actual_capture_dimensions(job, scale)
        exceeds_edge = args.max_capture_edge > 0 and max(width, height) > args.max_capture_edge
        exceeds_pixels = args.max_capture_pixels > 0 and width * height > args.max_capture_pixels
        if not exceeds_edge and not exceeds_pixels:
            break
        scale -= 1
    return scale


def effective_capture_fps(job: ExportJob, args: argparse.Namespace, scale: int) -> int:
    requested_fps = max(1, int(args.fps))
    fps = requested_fps
    width, height = actual_capture_dimensions(job, scale)
    is_large_capture = scale < render_scale(args) or (
        args.large_capture_pixels > 0 and width * height > args.large_capture_pixels
    )
    if not is_large_capture:
        return fps
    if args.large_capture_fps > 0:
        fps = min(fps, int(args.large_capture_fps))
    if args.max_deterministic_megapixel_frames > 0:
        budget = args.max_deterministic_megapixel_frames * 1_000_000
        max_fps = math.floor(budget / max(1.0, width * height * job.duration_seconds))
        fps = min(fps, max_fps)
    minimum = min(requested_fps, max(1, int(args.min_large_capture_fps)))
    return max(minimum, fps)


def actual_capture_dimensions(job: ExportJob, scale: int) -> tuple[int, int]:
    return job.capture_width * scale, job.capture_height * scale


def should_crop_job(job: ExportJob, args: argparse.Namespace) -> bool:
    if job.group == "battle_ready":
        return not args.no_battle_crop
    if job.group == "card":
        return not args.no_card_crop
    return False


def job_uses_alpha(job: ExportJob, args: argparse.Namespace) -> bool:
    return job.group != "battle_ready" or args.battle_transparent


def scaled_crop_padding(job: ExportJob, args: argparse.Namespace, scale: int) -> int:
    padding = args.battle_crop_padding if job.group == "battle_ready" else args.card_crop_padding
    return int(round(padding * scale))


def scaled_crop_dimensions(crop: VideoCrop, scale: int) -> tuple[int, int]:
    return even_floor(crop.width / scale), even_floor(crop.height / scale)


def encode_frames(
    frame_dir: Path,
    target: Path,
    args: argparse.Namespace,
    width: int,
    height: int,
    crop: VideoCrop | None = None,
    capture_fps: int | None = None,
    output_fps: int | None = None,
    alpha: bool = True,
) -> None:
    filters = encode_filters(width, height, crop, output_fps or args.fps)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-framerate",
        str(capture_fps or args.fps),
        "-i",
        str(frame_dir / "frame_%06d.png"),
        "-vf",
        filters,
        "-an",
        "-c:v",
        "libvpx-vp9",
        *vp9_encoder_options(args),
        "-pix_fmt",
        "yuva420p" if alpha else "yuv420p",
        "-auto-alt-ref",
        "0",
        "-b:v",
        "0",
        "-crf",
        str(args.vp9_crf),
        str(target),
    ]
    if alpha:
        command[-1:-1] = ["-metadata:s:v:0", "alpha_mode=1"]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg frame encode failed: " + result.stderr.strip())
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError("ffmpeg frame encode produced an empty file")


def encode_filters(width: int, height: int, crop: VideoCrop | None = None, fps: int | None = None) -> str:
    filters = []
    if crop is not None:
        filters.append(f"crop={crop.width}:{crop.height}:{crop.x}:{crop.y}")
    if fps is not None:
        filters.append(f"fps={max(1, int(fps))}")
    filters.append(f"scale={width}:{height}:flags=lanczos")
    return ",".join(filters)


def vp9_encoder_options(args: argparse.Namespace) -> list[str]:
    options = [
        "-deadline",
        args.vp9_deadline,
        "-cpu-used",
        str(args.vp9_cpu_used),
        "-row-mt",
        "1",
    ]
    if args.ffmpeg_threads > 0:
        options.extend(["-threads", str(args.ffmpeg_threads)])
    return options


def detect_video_crop(path: Path, padding: int, alpha: bool) -> VideoCrop | None:
    width, height = video_dimensions(path)
    command = [
        "ffmpeg",
        "-hide_banner",
    ]
    if alpha:
        command.extend(["-c:v", "libvpx-vp9"])
    command.extend([
        "-i",
        str(path),
        "-vf",
        cropdetect_filter(alpha),
        "-frames:v",
        "180",
        "-f",
        "null",
        "-",
    ])
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg crop detection failed: " + result.stderr.strip())

    return detect_crop_from_output(width, height, result.stderr, padding)


def detect_frame_crop(frame_dir: Path, frame_count: int, padding: int, alpha: bool, opaque_threshold: int) -> VideoCrop | None:
    width, height = video_dimensions(frame_dir / "frame_000000.png")
    if not alpha:
        return detect_opaque_frame_crop(frame_dir, frame_count, width, height, padding, opaque_threshold)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(frame_dir / "frame_%06d.png"),
        "-vf",
        cropdetect_filter(alpha),
        "-frames:v",
        str(min(180, frame_count)),
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg frame crop detection failed: " + result.stderr.strip())

    return detect_crop_from_output(width, height, result.stderr, padding)


def detect_opaque_frame_crop(
    frame_dir: Path,
    frame_count: int,
    width: int,
    height: int,
    padding: int,
    threshold: int,
) -> VideoCrop | None:
    similarity = max(0.0, min(1.0, max(0, int(threshold)) / 255.0))
    command = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(frame_dir / "frame_%06d.png"),
        "-vf",
        f"colorkey=0x0f121d:similarity={similarity:.4f}:blend=0,format=rgba,alphaextract,cropdetect=limit=1:round=2:reset=0",
        "-frames:v",
        str(min(180, frame_count)),
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg opaque frame crop detection failed: " + result.stderr.strip())
    return detect_crop_from_output(width, height, result.stderr, padding)


def cropdetect_filter(alpha: bool) -> str:
    if alpha:
        return "format=rgba,alphaextract,cropdetect=limit=1:round=2:reset=0"
    return "cropdetect=limit=40:round=2:reset=0"


def detect_crop_from_output(width: int, height: int, output: str, padding: int) -> VideoCrop | None:
    bounds: list[tuple[int, int, int, int]] = []
    for match in re.finditer(r"x1:(\d+)\s+x2:(\d+)\s+y1:(\d+)\s+y2:(\d+)", output):
        x1, x2, y1, y2 = (int(group) for group in match.groups())
        if x2 > x1 and y2 > y1:
            bounds.append((x1, x2, y1, y2))
    if not bounds:
        return None

    return crop_from_bounds(width, height, bounds, padding)


def crop_from_bounds(width: int, height: int, bounds: list[tuple[int, int, int, int]], padding: int) -> VideoCrop | None:
    if not bounds:
        return None
    pad = max(0, int(padding))
    x1 = max(0, min(item[0] for item in bounds) - pad)
    x2 = min(width - 1, max(item[1] for item in bounds) + pad)
    y1 = max(0, min(item[2] for item in bounds) - pad)
    y2 = min(height - 1, max(item[3] for item in bounds) + pad)
    crop_width = even_floor(x2 - x1 + 1)
    crop_height = even_floor(y2 - y1 + 1)
    x = clamp_even(x1, 0, max(0, width - crop_width))
    y = clamp_even(y1, 0, max(0, height - crop_height))

    if crop_width >= width and crop_height >= height:
        return None
    return VideoCrop(x=x, y=y, width=crop_width, height=crop_height, source_width=width, source_height=height)


def video_dimensions(path: Path) -> tuple[int, int]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        str(path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffprobe failed: " + result.stderr.strip())
    match = re.search(r"(\d+)x(\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not read video dimensions for {path}")
    return int(match.group(1)), int(match.group(2))


def video_duration(path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffprobe duration failed: " + result.stderr.strip())
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        duration = packet_duration(path)
    if duration <= 0:
        raise RuntimeError(f"Video duration was not positive for {path}")
    return duration


def packet_duration(path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts_time,duration_time",
        "-of",
        "csv=p=0",
        str(path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffprobe packet duration failed: " + result.stderr.strip())
    end_time = 0.0
    for line in result.stdout.splitlines():
        values = [part.strip() for part in line.split(",") if part.strip() and part.strip() != "N/A"]
        if not values:
            continue
        try:
            pts = float(values[0])
            frame_duration = float(values[1]) if len(values) > 1 else 0.0
        except ValueError:
            continue
        end_time = max(end_time, pts + frame_duration)
    if end_time <= 0:
        raise RuntimeError(f"Could not read video duration for {path}")
    return end_time


def transcode_video(
    source: Path,
    target: Path,
    args: argparse.Namespace,
    width: int,
    height: int,
    crop: VideoCrop | None = None,
    alpha: bool = True,
) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(source),
        "-vf",
        encode_filters(width, height, crop),
        "-an",
        "-c:v",
        "libvpx-vp9",
        *vp9_encoder_options(args),
        "-pix_fmt",
        "yuva420p" if alpha else "yuv420p",
        "-auto-alt-ref",
        "0",
        "-b:v",
        "0",
        "-crf",
        str(args.vp9_crf),
        str(target),
    ]
    if alpha:
        command[-1:-1] = ["-metadata:s:v:0", "alpha_mode=1"]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg transcode failed: " + result.stderr.strip())
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError("ffmpeg transcode produced an empty file")


def even_floor(value: int) -> int:
    number = max(2, int(value))
    return number if number % 2 == 0 else number - 1


def clamp_even(value: int, minimum: int, maximum: int) -> int:
    clamped = max(minimum, min(maximum, int(value)))
    if clamped % 2 == 0:
        return clamped
    return clamped - 1 if clamped > minimum else clamped + 1


def wait_for_capture(server: ExportServer, job_id: str, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"ok": False, "id": job_id, "message": f"timed out after {timeout:.1f}s"}
        try:
            result = server.results.get(timeout=min(0.5, remaining))
        except queue.Empty:
            continue
        if result.get("id") == job_id:
            return result
        server.results.put(result)
        time.sleep(0.05)


def error_payload(job: ExportJob, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "key": job.key,
        "character_id": job.character.id,
        "character": job.character.name,
        "group": job.group,
        "source_json": rel(job.source_json),
        "animations": list(job.animations),
        "message": message,
    }


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def write_manifest(manifest: dict[str, Any]) -> None:
    L2D_ROOT.mkdir(parents=True, exist_ok=True)
    path = L2D_ROOT / "export_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def print_summary(manifest: dict[str, Any]) -> None:
    print(
        "Done: "
        f"{len(manifest['jobs'])} exported, "
        f"{len(manifest['skipped'])} skipped, "
        f"{len(manifest['errors'])} errors."
    )
    if manifest["errors"]:
        print("First errors:")
        for item in manifest["errors"][:10]:
            print(f"- {item.get('key')}: {item.get('message')}")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
