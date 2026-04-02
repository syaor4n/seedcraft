#!/usr/bin/env python3
"""
SeedCraft — Claude Code to Minecraft Seed Generator

Reads Claude Code session data from ~/.claude/, computes a climate profile
from usage statistics, and selects a curated Minecraft seed whose spawn
biome genuinely matches the profile.

Usage:
    python3 generate_seed.py --all
    python3 generate_seed.py --project "my-project"
    python3 generate_seed.py --list
    python3 generate_seed.py --all --stats-only
    python3 generate_seed.py --all --json
"""

import argparse
import hashlib
import json
import math
import sys
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
# Support both installed skill layout (scripts/seeds_db.json)
# and repo layout (data/seeds_db.json)
_DB_CANDIDATES = [
    SCRIPT_DIR / "seeds_db.json",
    SCRIPT_DIR.parent / "data" / "seeds_db.json",
]
SEEDS_DB_PATH = next((p for p in _DB_CANDIDATES if p.exists()), _DB_CANDIDATES[0])

# Tool categories for ratio computation
TOOLS_READ = {"Read", "Grep", "Glob", "ToolSearch"}
TOOLS_WRITE = {"Write", "Edit", "NotebookEdit"}
TOOLS_EXECUTE = {"Bash"}
TOOLS_ORCHESTRATE = {"Agent", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "TaskStop", "TaskOutput"}

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def normalize(value, breakpoints):
    """Piecewise linear interpolation between (raw, normalized) breakpoints."""
    if value <= breakpoints[0][0]:
        return breakpoints[0][1]
    if value >= breakpoints[-1][0]:
        return breakpoints[-1][1]
    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i + 1]
        if x0 <= value <= x1:
            t = (value - x0) / (x1 - x0) if x1 != x0 else 0
            return y0 + t * (y1 - y0)
    return breakpoints[-1][1]


def fmt(n):
    """Format integer with thousands separators."""
    return f"{n:,}"

# ---------------------------------------------------------------------------
# Parsing — real Claude Code JSONL format
# ---------------------------------------------------------------------------

def parse_session_file(filepath):
    """Parse a Claude Code JSONL session file and extract stats.

    The real format uses top-level ``type`` (user / assistant / system /
    progress) with message content nested under ``msg["message"]``.
    """
    stats = {
        "messages": 0,
        "human_messages": 0,
        "assistant_messages": 0,
        "tool_calls": 0,
        "tool_calls_by_name": Counter(),
        "tools_used": set(),
        "total_chars": 0,
        "timestamps": [],
        "models_used": Counter(),
        "error_count": 0,
        "agent_calls": 0,
    }

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")
                ts = msg.get("timestamp")
                if ts is not None:
                    stats["timestamps"].append(ts)

                # --- user messages ---
                if msg_type == "user":
                    stats["messages"] += 1
                    stats["human_messages"] += 1
                    inner = msg.get("message", {})
                    _count_content_chars(inner.get("content", ""), stats)
                    _scan_tool_results(inner.get("content", []), stats)

                # --- assistant messages ---
                elif msg_type == "assistant":
                    stats["messages"] += 1
                    stats["assistant_messages"] += 1
                    inner = msg.get("message", {})
                    model = inner.get("model", "unknown")
                    if model and model != "<synthetic>":
                        stats["models_used"][model] += 1
                    _count_content_chars(inner.get("content", ""), stats)
                    _scan_tool_uses(inner.get("content", []), stats)

    except (OSError, IOError) as exc:
        print(f"  Warning: could not read {filepath}: {exc}", file=sys.stderr)

    return stats


def _count_content_chars(content, stats):
    """Accumulate character count from string or block-list content."""
    if isinstance(content, str):
        stats["total_chars"] += len(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if text:
                    stats["total_chars"] += len(str(text))


def _scan_tool_uses(content, stats):
    """Scan assistant content blocks for tool_use entries."""
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            name = block.get("name", "unknown")
            stats["tool_calls"] += 1
            stats["tool_calls_by_name"][name] += 1
            stats["tools_used"].add(name)
            if name == "Agent":
                stats["agent_calls"] += 1


def _scan_tool_results(content, stats):
    """Scan user content blocks for tool_result entries (error counting)."""
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            if block.get("is_error"):
                stats["error_count"] += 1

# ---------------------------------------------------------------------------
# Stats aggregation
# ---------------------------------------------------------------------------

def merge_stats(all_stats):
    merged = {
        "messages": 0,
        "human_messages": 0,
        "assistant_messages": 0,
        "tool_calls": 0,
        "tool_calls_by_name": Counter(),
        "tools_used": set(),
        "total_chars": 0,
        "timestamps": [],
        "models_used": Counter(),
        "error_count": 0,
        "agent_calls": 0,
    }
    for s in all_stats:
        merged["messages"] += s["messages"]
        merged["human_messages"] += s["human_messages"]
        merged["assistant_messages"] += s["assistant_messages"]
        merged["tool_calls"] += s["tool_calls"]
        merged["tool_calls_by_name"] += s["tool_calls_by_name"]
        merged["tools_used"] |= s["tools_used"]
        merged["total_chars"] += s["total_chars"]
        merged["timestamps"].extend(s["timestamps"])
        merged["models_used"] += s["models_used"]
        merged["error_count"] += s["error_count"]
        merged["agent_calls"] += s["agent_calls"]
    return merged


def _ts_to_epoch_ms(ts):
    """Convert a timestamp (int epoch-ms, float epoch-s, or ISO-8601 string) to epoch ms."""
    if isinstance(ts, (int, float)):
        # Already numeric — assume ms if large, seconds if small
        return int(ts) if ts > 1e12 else int(ts * 1000)
    if isinstance(ts, str):
        try:
            cleaned = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except (ValueError, AttributeError):
            return None
    return None


def _detect_active_segments(epoch_list, gap_ms=30 * 60 * 1000):
    """Split a sorted list of epoch-ms timestamps into active segments.

    Returns a list of segment durations (in ms), excluding zero-length segments.
    A new segment starts when the gap between consecutive timestamps exceeds gap_ms.
    """
    if len(epoch_list) < 2:
        return []
    segments = []
    seg_start = epoch_list[0]
    prev = epoch_list[0]
    for t in epoch_list[1:]:
        if t - prev > gap_ms:
            dur = prev - seg_start
            if dur > 0:
                segments.append(dur)
            seg_start = t
        prev = t
    dur = prev - seg_start
    if dur > 0:
        segments.append(dur)
    return segments


def compute_derived_stats(stats, session_count, project_count, project_names,
                          per_session_durations=None):
    """Add higher-level derived metrics to the stats dict (mutates)."""
    stats["session_count"] = session_count
    stats["project_count"] = project_count
    stats["project_names"] = sorted(project_names)

    # Convert all timestamps to epoch-ms
    epoch_list = []
    for ts in stats["timestamps"]:
        ms = _ts_to_epoch_ms(ts)
        if ms is not None:
            epoch_list.append(ms)
    epoch_list.sort()

    # Duration estimation from timestamps
    if len(epoch_list) >= 2:
        stats["total_duration_ms"] = epoch_list[-1] - epoch_list[0]
    else:
        stats["total_duration_ms"] = 0

    # Per-session durations: prefer pre-computed per-file durations (accurate)
    # over merged-timestamp gap detection (can inflate when sessions overlap)
    if per_session_durations:
        session_durations = per_session_durations
    else:
        session_durations = _detect_active_segments(epoch_list)
    stats["session_durations"] = session_durations
    stats["avg_session_duration_ms"] = (
        sum(session_durations) / len(session_durations) if session_durations else 0
    )
    stats["total_active_ms"] = sum(session_durations)

    # Hour-of-day distribution
    hour_dist = [0] * 24
    for ms in epoch_list:
        try:
            dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
            hour_dist[dt.hour] += 1
        except (ValueError, OSError, OverflowError):
            pass
    stats["hour_distribution"] = hour_dist
    night_hours = sum(hour_dist[h] for h in range(0, 6)) + sum(hour_dist[h] for h in range(22, 24))
    day_hours = sum(hour_dist[h] for h in range(6, 22))
    stats["night_ratio"] = night_hours / max(1, night_hours + day_hours)

    # Tool category counts
    by_name = stats["tool_calls_by_name"]
    stats["read_calls"] = sum(by_name.get(t, 0) for t in TOOLS_READ)
    stats["write_calls"] = sum(by_name.get(t, 0) for t in TOOLS_WRITE)
    stats["execute_calls"] = sum(by_name.get(t, 0) for t in TOOLS_EXECUTE)
    stats["orchestrate_calls"] = sum(by_name.get(t, 0) for t in TOOLS_ORCHESTRATE)
    stats["mcp_calls"] = sum(v for k, v in by_name.items() if k.startswith("mcp__"))

    # Ratios
    total_rw = stats["read_calls"] + stats["write_calls"]
    stats["write_ratio"] = stats["write_calls"] / max(1, total_rw)
    stats["tools_per_message"] = stats["tool_calls"] / max(1, stats["messages"])
    stats["error_rate"] = stats["error_count"] / max(1, stats["tool_calls"])

    return stats

# ---------------------------------------------------------------------------
# Climate profile computation
# ---------------------------------------------------------------------------

def compute_climate_profile(stats):
    """Map aggregated stats to Minecraft climate parameters.

    Output ranges are calibrated to MC's actual biome parameter space so that
    even minimal-usage profiles land in a region where real biomes exist.
    MC biome parameters cluster roughly in:
        temperature     0.17 – 0.88
        humidity        0.26 – 0.73
        continentalness 0.42 – 0.82
        erosion         0.15 – 0.85
        weirdness       0.16 – 0.81
    """
    profile = {}

    # Temperature: more messages = hotter world
    # MC range: ~0.17 (ice_spikes) to ~0.88 (badlands)
    profile["temperature"] = normalize(stats["messages"], [
        (0, 0.15), (50, 0.18), (200, 0.22), (1000, 0.32),
        (5000, 0.48), (20000, 0.65), (50000, 0.78),
        (100000, 0.88), (500000, 0.92),
    ])

    # Humidity: more total tool calls = lusher world
    # MC range: ~0.26 (sunflower_plains) to ~0.73 (lush_caves)
    profile["humidity"] = normalize(stats["tool_calls"], [
        (0, 0.25), (10, 0.27), (50, 0.30), (200, 0.35),
        (1000, 0.42), (5000, 0.55), (15000, 0.65),
        (30000, 0.72), (60000, 0.78), (200000, 0.82),
    ])

    # Continentalness: more write/edit calls = more continental (builder)
    # MC range: ~0.42 (ocean/beach) to ~0.82 (dripstone_caves)
    profile["continentalness"] = normalize(stats["write_calls"], [
        (0, 0.40), (5, 0.42), (20, 0.45), (100, 0.50),
        (500, 0.58), (2000, 0.67), (5000, 0.75),
        (10000, 0.82), (30000, 0.88),
    ])

    # Erosion (low = tall mountains): more total active time = less eroded = taller
    # MC range: ~0.15 (stony_peaks) to ~0.85 (swamp)
    total_hours = stats["total_active_ms"] / 3_600_000
    profile["erosion"] = normalize(total_hours, [
        (0, 0.82), (0.5, 0.75), (2, 0.65), (5, 0.55),
        (12, 0.45), (24, 0.37), (60, 0.28),
        (120, 0.20), (500, 0.15),
    ])

    # Weirdness: tool diversity
    # MC range: ~0.16 (jagged_peaks) to ~0.81 (frozen_peaks)
    unique_tools = len(stats["tools_used"])
    profile["weirdness"] = normalize(unique_tools, [
        (0, 0.15), (2, 0.18), (5, 0.23), (10, 0.32),
        (20, 0.45), (35, 0.58), (50, 0.68),
        (75, 0.78), (120, 0.85),
    ])

    # Structure density: agent + orchestration calls
    orchestrate = stats["agent_calls"] + stats["orchestrate_calls"]
    profile["structure_density"] = normalize(orchestrate, [
        (0, 0.00), (5, 0.10), (15, 0.22), (40, 0.38),
        (100, 0.55), (250, 0.72), (500, 0.88),
        (1000, 0.95), (3000, 1.00),
    ])

    # Biome diversity: project count
    profile["biome_diversity"] = normalize(stats["project_count"], [
        (1, 0.08), (2, 0.18), (3, 0.28), (5, 0.42),
        (8, 0.58), (12, 0.72), (20, 0.88),
        (40, 0.96), (80, 1.00),
    ])

    return profile

# ---------------------------------------------------------------------------
# Seed database & selection
# ---------------------------------------------------------------------------

def load_seed_database(db_path=None):
    """Load the curated seed database JSON."""
    path = db_path or SEEDS_DB_PATH
    if not path.exists():
        print(f"Error: seed database not found at {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r") as fh:
        data = json.load(fh)
    return data["seeds"]


def stats_fingerprint(stats):
    """Deterministic hash of stats for tiebreaking among equally-close seeds."""
    canonical = json.dumps({
        "messages": stats["messages"],
        "tool_calls": stats["tool_calls"],
        "unique_tools": sorted(stats["tools_used"]),
        "total_chars": stats["total_chars"],
        "project_names": stats["project_names"],
    }, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_unique_seed(stats):
    """Hash ALL stats into a unique 32-bit Bedrock-compatible seed.

    Unlike ``select_seed`` which picks from a curated database (biome-matched),
    this produces a completely unique seed by hashing every stat dimension.
    The biome is unknown — discover it in Minecraft or on Chunkbase.
    """
    import struct
    canonical = json.dumps({
        "messages": stats["messages"],
        "human_messages": stats["human_messages"],
        "assistant_messages": stats["assistant_messages"],
        "tool_calls": stats["tool_calls"],
        "unique_tools": sorted(stats["tools_used"]),
        "total_chars": stats["total_chars"],
        "project_names": stats["project_names"],
        "session_count": stats["session_count"],
        "total_active_ms": stats["total_active_ms"],
        "error_count": stats["error_count"],
        "agent_calls": stats["agent_calls"],
        "read_calls": stats["read_calls"],
        "write_calls": stats["write_calls"],
        "execute_calls": stats["execute_calls"],
        "mcp_calls": stats["mcp_calls"],
        "models": sorted(stats["models_used"].keys()),
    }, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    # First 4 bytes -> signed 32-bit int (Bedrock-compatible)
    seed = struct.unpack(">i", digest[:4])[0]
    return seed


CLIMATE_WEIGHTS = {
    "temperature": 1.5,
    "humidity": 1.5,
    "continentalness": 1.0,
    "erosion": 1.2,
    "weirdness": 0.8,
    "biome_diversity": 0.6,
}


def _climate_distance(a, b):
    """Weighted euclidean distance between two climate dicts."""
    return math.sqrt(sum(
        CLIMATE_WEIGHTS[k] * (a.get(k, 0.5) - b.get(k, 0.5)) ** 2
        for k in CLIMATE_WEIGHTS
    ))


def select_seed(profile, seeds_db, stats):
    """Two-stage seed selection for precise biome matching.

    Stage 1: Find the best-matching BIOME TYPE by comparing the user's
             climate profile against the average climate center of each biome.
    Stage 2: Among all seeds of that biome, find the closest individual seed.
    Stage 3: Hash-based deterministic tiebreak among top-5 within the biome.

    This guarantees the biome is always the conceptually correct one — the hash
    only varies the specific seed within the correct biome.
    """
    if not seeds_db:
        return {"seed": 0, "spawn_biome": "plains",
                "climate": {k: 0.5 for k in CLIMATE_WEIGHTS},
                "biome_diversity": 1}

    # Stage 1: Group seeds by biome, compute biome centers
    biome_groups = defaultdict(list)
    for entry in seeds_db:
        if entry["spawn_biome"] == "unknown":
            continue
        biome_groups[entry["spawn_biome"]].append(entry)

    best_biome = None
    best_dist = float("inf")
    for biome, entries in biome_groups.items():
        center = {}
        for k in CLIMATE_WEIGHTS:
            if k == "biome_diversity":
                center[k] = sum(min(e.get("biome_diversity", 5) / 15.0, 1.0) for e in entries) / len(entries)
            else:
                center[k] = sum(e["climate"][k] for e in entries) / len(entries)
        dist = _climate_distance(profile, center)
        if dist < best_dist or (dist == best_dist and (best_biome is None or biome < best_biome)):
            best_dist = dist
            best_biome = biome

    # Stage 2: Find closest seeds within the winning biome
    candidates = biome_groups[best_biome]
    scored = []
    for entry in candidates:
        # Merge climate dict with normalized biome_diversity for distance calc
        climate_with_bd = dict(entry["climate"])
        climate_with_bd["biome_diversity"] = min(entry.get("biome_diversity", 5) / 15.0, 1.0)
        dist = _climate_distance(profile, climate_with_bd)
        scored.append((dist, entry))
    scored.sort(key=lambda x: (x[0], x[1]["seed"]))

    # Stage 3: Prefer Bedrock-compatible (32-bit) seeds, then tiebreak
    bedrock_safe = [(d, e) for d, e in scored if _is_bedrock_safe(e["seed"])]
    pool = bedrock_safe if len(bedrock_safe) >= 2 else scored
    top_n = min(20, len(pool))
    fingerprint = stats_fingerprint(stats)

    # Structure density shifts the pick toward seeds with higher biome diversity
    sd = profile.get("structure_density", 0)
    if sd > 0.3 and top_n > 3:
        diversity_sorted = sorted(pool[:top_n], key=lambda x: x[1].get("biome_diversity", 0), reverse=True)
        pick_n = max(3, round(top_n * (1 - sd * 0.7)))
        idx = int(fingerprint[:8], 16) % pick_n
        return diversity_sorted[idx][1]
    else:
        idx = int(fingerprint[:8], 16) % top_n
        return pool[idx][1]


def _is_bedrock_safe(seed):
    """Check if a seed fits in 32-bit signed range (Bedrock compatible)."""
    return -2147483648 <= seed <= 2147483647


def _make_share_card(seed, biome_display, stats, profile=None, unique=False):
    """Build a share card text and pre-filled tweet URL."""
    total_h = stats["total_active_ms"] / 3_600_000
    msgs = fmt(stats["messages"])
    tools = fmt(stats["tool_calls"])

    if unique:
        share_text = (
            f"#SeedCraft | UNIQUE | {msgs} msgs, {tools} tools, {total_h:.0f}h coding"
        )
        tweet_text = (
            f"My Claude Code stats as a Minecraft seed: UNIQUE\n\n"
            f"{msgs} messages | {tools} tools | {total_h:.0f}h coded\n\n"
            f"What's YOUR coding world?\n"
            f"seedcraft.dev\n\n"
            f"#SeedCraft #ClaudeCode #Minecraft"
        )
    else:
        temp = int(profile["temperature"] * 100)
        humid = int(profile["humidity"] * 100)
        elev = int((1 - profile["erosion"]) * 100)
        share_text = (
            f"#SeedCraft | {biome_display} | {temp}% hot, {humid}% humid, "
            f"{elev}% elevation | {total_h:.0f}h coding"
        )
        tweet_text = (
            f"My Claude Code stats as a Minecraft world: {biome_display}\n\n"
            f"{temp}% hot | {humid}% humid | {elev}% elevation\n"
            f"{msgs} messages | {tools} tools | {total_h:.0f}h coded\n\n"
            f"What's YOUR coding world?\n"
            f"seedcraft.dev\n\n"
            f"#SeedCraft #ClaudeCode #Minecraft"
        )

    tweet_url = "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(tweet_text)

    # Pre-filled gallery submission URL
    gallery_params_dict = {
        "seed": seed,
        "comment": f"{total_h:.0f}h of coding, {stats['messages']:,} messages",
    }
    gallery_params_dict["stat_messages"] = str(stats["messages"])
    gallery_params_dict["stat_tool_calls"] = str(stats["tool_calls"])
    gallery_params_dict["stat_active_hours"] = f"{stats['total_active_hours']:.1f}"
    if not unique:
        gallery_params_dict["biome"] = biome_display.lower().replace(" ", "_")
        for key in ("temperature", "humidity", "continentalness", "erosion", "weirdness", "structure_density", "biome_diversity"):
            gallery_params_dict[key] = f"{profile[key]:.4f}"
    gallery_params = urllib.parse.urlencode(gallery_params_dict)
    gallery_url = f"https://seedcraft.dev/gallery?share&{gallery_params}"

    return share_text, tweet_url, gallery_url

# ---------------------------------------------------------------------------
# Biome narration templates
# ---------------------------------------------------------------------------

BIOME_LABELS = {
    "desert":           "DESERT",
    "jungle":           "JUNGLE",
    "bamboo_jungle":    "BAMBOO JUNGLE",
    "sparse_jungle":    "SPARSE JUNGLE",
    "plains":           "PLAINS",
    "sunflower_plains": "SUNFLOWER PLAINS",
    "forest":           "FOREST",
    "birch_forest":     "BIRCH FOREST",
    "old_growth_birch_forest": "OLD GROWTH BIRCH FOREST",
    "dark_forest":      "DARK FOREST",
    "flower_forest":    "FLOWER FOREST",
    "taiga":            "TAIGA",
    "old_growth_spruce_taiga": "OLD GROWTH SPRUCE TAIGA",
    "old_growth_pine_taiga":   "OLD GROWTH PINE TAIGA",
    "snowy_plains":     "SNOWY PLAINS",
    "snowy_taiga":      "SNOWY TAIGA",
    "frozen_peaks":     "FROZEN PEAKS",
    "stony_peaks":      "STONY PEAKS",
    "jagged_peaks":     "JAGGED PEAKS",
    "snowy_slopes":     "SNOWY SLOPES",
    "savanna":          "SAVANNA",
    "savanna_plateau":  "SAVANNA PLATEAU",
    "windswept_savanna":"WINDSWEPT SAVANNA",
    "badlands":         "BADLANDS",
    "wooded_badlands":  "WOODED BADLANDS",
    "eroded_badlands":  "ERODED BADLANDS",
    "swamp":            "SWAMP",
    "mangrove_swamp":   "MANGROVE SWAMP",
    "mushroom_fields":  "MUSHROOM FIELDS",
    "ocean":            "OCEAN",
    "deep_ocean":       "DEEP OCEAN",
    "warm_ocean":       "WARM OCEAN",
    "lukewarm_ocean":   "LUKEWARM OCEAN",
    "cold_ocean":       "COLD OCEAN",
    "frozen_ocean":     "FROZEN OCEAN",
    "deep_lukewarm_ocean": "DEEP LUKEWARM OCEAN",
    "deep_cold_ocean":  "DEEP COLD OCEAN",
    "deep_frozen_ocean":"DEEP FROZEN OCEAN",
    "beach":            "BEACH",
    "snowy_beach":      "SNOWY BEACH",
    "stony_shore":      "STONY SHORE",
    "cherry_grove":     "CHERRY GROVE",
    "meadow":           "MEADOW",
    "windswept_hills":  "WINDSWEPT HILLS",
    "windswept_forest": "WINDSWEPT FOREST",
    "grove":            "GROVE",
    "dripstone_caves":  "DRIPSTONE CAVES",
    "lush_caves":       "LUSH CAVES",
    "ice_spikes":       "ICE SPIKES",
    "pale_garden":      "PALE GARDEN",
}

BIOME_NARRATIVES = {
    "desert": (
        "Your {messages} messages scorched the atmosphere."
        " The desert reflects a direct, focused coding style"
        " — maximum intent, minimum overhead."
    ),
    "jungle": (
        "Your {messages} messages raised the temperature while"
        " {tool_calls} tool calls nurtured dense vegetation."
        " A lush jungle forged by relentless productivity."
    ),
    "bamboo_jungle": (
        "Extreme heat from {messages} messages and extreme humidity"
        " from {tool_calls} tool calls. Your world is a wall of bamboo"
        " — impenetrable productivity."
    ),
    "plains": (
        "Balanced and steady. Moderate warmth, moderate humidity"
        " across {projects} projects. A world of open possibility."
    ),
    "sunflower_plains": (
        "A gentle coder's world. Your {messages} messages bring mild"
        " warmth, and your balanced tooling lets sunflowers bloom."
    ),
    "forest": (
        "A natural equilibrium of conversation and tooling across"
        " {projects} projects. The forest mirrors a healthy workflow."
    ),
    "birch_forest": (
        "Light and organized. Your sessions average {avg_min:.0f} minutes"
        " — short, productive, and bright like birch bark."
    ),
    "dark_forest": (
        "Dense tool usage casts deep shadows. {tool_calls} tool calls"
        " created a canopy so thick, hostile mobs lurk below."
    ),
    "flower_forest": (
        "Your {unique_tools} unique tools paint the forest floor"
        " with color. A diverse, beautiful workflow."
    ),
    "taiga": (
        "Cool and methodical. Your {messages} messages keep things"
        " grounded, like the spruce forests of the taiga."
    ),
    "old_growth_spruce_taiga": (
        "Ancient trees for a veteran coder. {hours:.0f} hours of"
        " sessions grew old-growth spruce that tower above all."
    ),
    "snowy_plains": (
        "A quiet, pristine world. Your {messages} messages leave"
        " careful footprints in fresh snow. The snowy plains"
        " reward a measured, deliberate approach."
    ),
    "snowy_taiga": (
        "A cool, quiet world. Your moderate pace across {projects}"
        " projects keeps things frosty but alive with spruce."
    ),
    "frozen_peaks": (
        "Minimal messages but {hours:.0f} hours of marathon sessions"
        " raised frozen peaks. Quiet intensity at its finest."
    ),
    "jagged_peaks": (
        "{hours:.0f} hours of relentless sessions pushed the terrain"
        " into jagged spires. These peaks were forged by persistence."
    ),
    "stony_peaks": (
        "Hot climate meets extreme elevation. Your {messages} messages"
        " heat the stone while {hours:.0f} hours raised the peaks."
    ),
    "savanna": (
        "Warm but not tropical. Active messaging with selective"
        " tool usage creates wide-open savanna — efficient and expansive."
    ),
    "badlands": (
        "Your {messages} messages pushed heat to the extreme."
        " {hours:.0f} hours of intense sessions sculpted red mesas"
        " from the scorched earth."
    ),
    "swamp": (
        "High humidity from {tool_calls} tool calls meets moderate"
        " warmth. The swamp mirrors your tool-heavy, exploratory"
        " workflow."
    ),
    "mangrove_swamp": (
        "Tropical heat and {tool_calls} tool calls saturated the air."
        " A tangled mangrove where your code roots run deep."
    ),
    "mushroom_fields": (
        "With {unique_tools} unique tools — the most exotic arsenal —"
        " your world manifests as the rarest biome. Pure weirdness."
    ),
    "ocean": (
        "A reader more than a writer. Your {reads} reads vs {writes}"
        " writes created vast oceans of knowledge. Dive deep."
    ),
    "deep_ocean": (
        "Read-heavy with {reads} reads, your code exploration carved"
        " deep ocean trenches. Knowledge runs unfathomably deep."
    ),
    "warm_ocean": (
        "Warm from {messages} messages and oceanic from your read-heavy"
        " style ({reads} reads). Coral reefs thrive in your workflow."
    ),
    "beach": (
        "Right at the boundary between reading and writing."
        " Your balanced ratio places you on the shore."
    ),
    "cherry_grove": (
        "Moderate and pleasant. Not too hot, not too cold."
        " Your {projects} projects bloom like cherry trees in spring."
    ),
    "meadow": (
        "A gentle, elevated meadow. Your {hours:.0f} hours of coding"
        " lifted the terrain, and balanced stats keep it serene."
    ),
    "windswept_hills": (
        "Your {hours:.0f} hours of sessions whipped up windswept hills."
        " Not the tallest, but the breeze of productivity is constant."
    ),
    "grove": (
        "Cool temperatures meet moderate elevation. Your measured"
        " approach across {projects} projects grew a peaceful grove."
    ),
    "dripstone_caves": (
        "Your {tool_calls} tool calls drilled deep into the earth."
        " Each call a stalactite dripping from the ceiling."
        " A subterranean coder's paradise."
    ),
    "lush_caves": (
        "Your {tool_calls} tool calls saturated the underground"
        " with humidity. Glow berries bloom in caverns"
        " carved by relentless exploration."
    ),
    "old_growth_birch_forest": (
        "Tall birch trees mark a seasoned coder. Your {messages}"
        " messages across {projects} projects grew an ancient,"
        " towering birch forest."
    ),
    "old_growth_pine_taiga": (
        "Massive pines for a veteran. Your {hours:.0f} hours of"
        " sessions and {messages} messages grew a primeval"
        " pine forest that dwarfs all others."
    ),
    "sparse_jungle": (
        "Warm from {messages} messages but not quite tropical."
        " Your {tool_calls} tool calls thin the jungle canopy"
        " into a sparse, navigable forest."
    ),
    "stony_shore": (
        "Where ocean meets continent. Your balanced read/write"
        " ratio ({reads} reads, {writes} writes) places you"
        " on a rugged, rocky shoreline."
    ),
    "snowy_beach": (
        "Cold and coastal. Few messages keep the temperature"
        " low, while your read-heavy style ({reads} reads)"
        " pulls the world toward the ocean."
    ),
    "savanna_plateau": (
        "Warm and elevated. Your {messages} messages bring heat"
        " while {hours:.0f} hours of sessions raised a flat-topped"
        " plateau above the savanna."
    ),
    "windswept_savanna": (
        "Hot and wild. Your {messages} messages scorch the landscape"
        " while {tool_calls} tool calls whip the savanna into"
        " windswept chaos."
    ),
    "wooded_badlands": (
        "Your {messages} messages and {writes} writes forged"
        " towering red mesas. Oak trees took root at the peaks."
        " A rare biome for a rare coding intensity."
    ),
    "eroded_badlands": (
        "Your {messages} messages scorched the earth. Time eroded"
        " the mesas into dramatic spires. {hours:.0f} hours of"
        " relentless coding carved this landscape."
    ),
    "snowy_slopes": (
        "Cold and elevated. Your modest message count keeps things"
        " frosty, while {hours:.0f} hours of sessions pushed the"
        " terrain upward into snow-covered slopes."
    ),
    "windswept_forest": (
        "Moderate temperatures meet high elevation. Your {hours:.0f}"
        " hours of marathon sessions raised windswept forests"
        " where the trees lean with the gale."
    ),
    "ice_spikes": (
        "Frozen and bizarre. Low message count keeps the world"
        " frigid, while your {unique_tools} unique tools sculpted"
        " towering ice spikes from the permafrost."
    ),
    "pale_garden": (
        "A ghostly, muted world. Your quiet, measured coding"
        " style across {projects} projects conjured the rarest"
        " biome — a pale garden shrouded in silence."
    ),
    "lukewarm_ocean": (
        "Mildly warm from {messages} messages, your read-heavy"
        " workflow ({reads} reads) created a lukewarm ocean."
        " Tropical fish swim just beneath the surface."
    ),
    "cold_ocean": (
        "Cool and deep. Your moderate messaging and read-heavy"
        " style ({reads} reads vs {writes} writes) chilled"
        " the waters into a cold ocean."
    ),
    "frozen_ocean": (
        "A frozen expanse. Few messages keep the world icy, and"
        " your read-heavy approach spreads vast, frozen oceans"
        " across the map."
    ),
    "deep_lukewarm_ocean": (
        "Deep and mildly warm. Your {reads} reads carved ocean"
        " trenches while {messages} messages kept the water"
        " just above freezing."
    ),
    "deep_cold_ocean": (
        "Frigid depths. Your read-heavy exploration ({reads}"
        " reads) plunged into cold, dark waters far from shore."
    ),
    "deep_frozen_ocean": (
        "The deepest freeze. Minimal messages and maximum reading"
        " created an ocean so cold and deep, icebergs scrape the"
        " ocean floor."
    ),
}

BIOME_FALLBACK = (
    "Your unique combination of {messages} messages, {tool_calls} tool"
    " calls across {projects} projects created a one-of-a-kind world."
)


def get_narrative(biome, stats):
    """Return the narration string for a biome, with stats interpolated."""
    template = BIOME_NARRATIVES.get(biome, BIOME_FALLBACK)
    total_hours = stats["total_active_ms"] / 3_600_000
    avg_min = stats["avg_session_duration_ms"] / 60_000
    return template.format(
        messages=fmt(stats["messages"]),
        tool_calls=fmt(stats["tool_calls"]),
        tpm=stats["tools_per_message"],
        projects=stats["project_count"],
        hours=total_hours,
        avg_min=avg_min,
        unique_tools=len(stats["tools_used"]),
        reads=fmt(stats["read_calls"]),
        writes=fmt(stats["write_calls"]),
    )

# ---------------------------------------------------------------------------
# Climate labels
# ---------------------------------------------------------------------------

def climate_label(param, value):
    """Human-readable label for a climate parameter value."""
    labels = {
        "temperature": [
            (0.15, "Frozen"), (0.30, "Cold"), (0.45, "Cool"),
            (0.60, "Mild"), (0.75, "Warm"), (0.90, "Hot"), (1.01, "Scorching"),
        ],
        "humidity": [
            (0.15, "Arid"), (0.30, "Dry"), (0.45, "Moderate"),
            (0.60, "Humid"), (0.75, "Wet"), (0.90, "Tropical"), (1.01, "Drenched"),
        ],
        "continentalness": [
            (0.20, "Deep Ocean"), (0.35, "Ocean"), (0.50, "Coast"),
            (0.65, "Inland"), (0.80, "Continental"), (1.01, "Far Inland"),
        ],
        "erosion": [
            (0.20, "Jagged Peaks"), (0.35, "Mountains"), (0.50, "Hills"),
            (0.65, "Rolling"), (0.80, "Gentle"), (1.01, "Flat"),
        ],
        "weirdness": [
            (0.20, "Normal"), (0.40, "Unusual"), (0.60, "Strange"),
            (0.80, "Bizarre"), (1.01, "Alien"),
        ],
        "structure_density": [
            (0.20, "Wilderness"), (0.40, "Sparse"), (0.60, "Settled"),
            (0.80, "Populated"), (1.01, "Metropolis"),
        ],
        "biome_diversity": [
            (0.20, "Monotone"), (0.40, "Limited"), (0.60, "Varied"),
            (0.80, "Diverse"), (1.01, "Kaleidoscope"),
        ],
    }
    for threshold, label in labels.get(param, []):
        if value < threshold:
            return label
    return "Unknown"

# ---------------------------------------------------------------------------
# Output rendering
# ---------------------------------------------------------------------------

BOX_W = 60  # inner width between the vertical bars


def _bar(value, width=12):
    filled = round(value * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _line(text="", w=BOX_W):
    visible_len = len(text)
    pad = w - 2 - visible_len
    if pad < 0:
        pad = 0
    return f"\u2551 {text}{' ' * pad} \u2551"


def _top(w=BOX_W):
    return "\u2554" + "\u2550" * (w) + "\u2557"


def _mid(w=BOX_W):
    return "\u2560" + "\u2550" * (w) + "\u2563"


def _bot(w=BOX_W):
    return "\u255a" + "\u2550" * (w) + "\u255d"


def _sep(char="\u2500", w=BOX_W):
    return _line(char * (w - 4), w)


def _serializable_stats(stats):
    """Return a JSON-serializable subset of stats."""
    return {
        "messages": stats["messages"],
        "human_messages": stats["human_messages"],
        "assistant_messages": stats["assistant_messages"],
        "tool_calls": stats["tool_calls"],
        "unique_tools": len(stats["tools_used"]),
        "top_tools": stats["tool_calls_by_name"].most_common(5),
        "total_chars": stats["total_chars"],
        "project_count": stats["project_count"],
        "project_names": stats["project_names"],
        "session_count": stats["session_count"],
        "total_active_hours": round(stats["total_active_ms"] / 3_600_000, 2),
        "avg_session_min": round(stats["avg_session_duration_ms"] / 60_000, 1),
        "tools_per_message": round(stats["tools_per_message"], 3),
        "write_ratio": round(stats["write_ratio"], 3),
        "error_rate": round(stats["error_rate"], 4),
    }


def _render_climate_bars(profile, lines):
    """Render climate profile bars into lines list."""
    params = [
        ("temperature",       "Temperature  "),
        ("humidity",          "Humidity     "),
        ("erosion",           "Elevation    "),
        ("continentalness",   "Continental  "),
        ("weirdness",         "Weirdness    "),
        ("structure_density", "Structures   "),
        ("biome_diversity",   "Diversity    "),
    ]
    for key, label in params:
        val = profile[key]
        display_val = (1.0 - val) if key == "erosion" else val
        pct = int(display_val * 100)
        cl = climate_label(key, val)
        bar = _bar(display_val)
        lines.append(_line(f"  {label} {bar}  {pct:>3}%  {cl}"))


def _render_stats_section(stats, mode_label, lines):
    """Render stats section into lines list."""
    a = lines.append
    a(_line(f"Stats ({mode_label})"))
    a(_line())
    a(_line(f"  Messages:     {fmt(stats['messages']):>10}  ({fmt(stats['human_messages'])} you / {fmt(stats['assistant_messages'])} AI)"))
    a(_line(f"  Tool calls:   {fmt(stats['tool_calls']):>10}  ({len(stats['tools_used'])} unique tools)"))
    a(_line(f"  Projects:     {stats['project_count']:>10}"))
    total_h = stats["total_active_ms"] / 3_600_000
    a(_line(f"  Active time:  {total_h:>9.1f}h  ({stats['session_count']} sessions)"))
    a(_line(f"  Characters:   {fmt(stats['total_chars']):>10}"))
    if stats.get("models_used"):
        top_model = stats["models_used"].most_common(1)[0][0]
        a(_line(f"  Top model:    {top_model:>10}"))
    # Top 5 tools
    top5 = stats["tool_calls_by_name"].most_common(5)
    if top5:
        a(_line())
        a(_line("  Top tools:"))
        for name, count in top5:
            a(_line(f"    {name:<20} {fmt(count):>8}"))


def render_stats_only(profile, stats, mode_label):
    """Print just the climate profile and stats without seed selection."""
    lines = []
    a = lines.append
    a(_top())
    a(_line("CLAUDE CODE STATS"))
    a(_mid())
    a(_line())
    a(_line("Climate Profile"))
    a(_line())
    _render_climate_bars(profile, lines)
    a(_line())
    a(_sep())
    _render_stats_section(stats, mode_label, lines)
    a(_line())
    a(_bot())
    print("\n".join(lines))


def render_output(seed_entry, profile, stats, mode_label):
    """Print the rich ASCII output card."""
    seed = seed_entry["seed"]
    biome = seed_entry["spawn_biome"]
    biome_display = BIOME_LABELS.get(biome, biome.upper().replace("_", " "))
    spawn_x = seed_entry.get("spawn_x", 0)
    spawn_z = seed_entry.get("spawn_z", 0)

    lines = []
    a = lines.append

    a(_top())
    a(_line("CLAUDE CODE -> MINECRAFT SEED"))
    a(_mid())
    a(_line())
    compat = "Java & Bedrock" if _is_bedrock_safe(seed) else "Java only"
    a(_line(f"Seed: {seed}"))
    a(_line(f"Spawn: ({spawn_x}, {spawn_z})  [{compat}]"))
    a(_line())
    a(_sep())
    a(_line("Climate Profile"))
    a(_line())
    _render_climate_bars(profile, lines)

    a(_line())
    a(_sep())
    a(_line(f"Predicted Biome: {biome_display}"))
    a(_line())

    # Narration — word-wrap at ~54 chars
    narrative = get_narrative(biome, stats)
    _wrap_lines(narrative, lines, 54)

    a(_line())
    a(_sep())
    _render_stats_section(stats, mode_label, lines)

    a(_line())
    a(_sep())
    a(_line("How to use:"))
    a(_line("  1. Copy the seed number"))
    a(_line("  2. Minecraft > Create New World > Seed"))
    a(_line("  3. Paste and play  (Java & Bedrock 1.18+)"))
    a(_line())
    a(_line(f"Preview: chunkbase.com/apps/seed-map#{seed}"))
    a(_line())
    a(_line("Deterministic: same stats = same world."))
    a(_bot())

    print("\n".join(lines))

    # Shareable one-liner (outside the box, easy to copy-paste)
    total_h = stats["total_active_ms"] / 3_600_000
    elev = int((1 - profile["erosion"]) * 100)
    temp = int(profile["temperature"] * 100)
    humid = int(profile["humidity"] * 100)
    print()
    print(f"  #SeedCraft | {biome_display} | {temp}% hot, {humid}% humid, {elev}% elevation | {total_h:.0f}h coding")
    print()


def _wrap_lines(text, lines, width):
    """Word-wrap text into _line() calls."""
    words = text.split()
    current = "  "
    for word in words:
        if len(current) + len(word) + 1 > width:
            if current.strip():
                lines.append(_line(current))
            current = "  " + word
        else:
            current += (" " if len(current) > 2 else "") + word
    if current.strip():
        lines.append(_line(current))

# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

def find_claude_dir():
    claude_dir = Path.home() / ".claude"
    if not claude_dir.exists():
        print("Error: ~/.claude directory not found.", file=sys.stderr)
        print("Make sure Claude Code is installed and has been used.", file=sys.stderr)
        sys.exit(1)
    return claude_dir


def find_projects(claude_dir):
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        return []
    return sorted(p for p in projects_dir.iterdir() if p.is_dir())


def find_session_files(directory):
    """Find all JSONL session files including subagent sessions.

    Includes both main sessions (``*.jsonl``) and subagent sessions
    (``*/subagents/*.jsonl``) since subagents represent real work — often
    99% of all session data.
    """
    files = set()
    # Main sessions at project root
    for fp in directory.glob("*.jsonl"):
        files.add(fp)
    # Subagent sessions
    for fp in directory.glob("*/subagents/*.jsonl"):
        files.add(fp)
    return sorted(files)


def pretty_project_name(raw_name):
    """Convert path-encoded project dir name to a readable name.

    ``-Users-jdoe-Sites-my-project`` -> ``my-project``
    ``-Users-jdoe-AndroidStudioProjects-App`` -> ``App``
    ``-`` -> ``(root)``
    """
    stripped = raw_name.strip("-")
    if not stripped:
        return "(root)"
    # The dir name encodes a filesystem path with - as separator.
    # Common patterns: Users-<user>-Sites-<project>
    #                  Users-<user>-<folder>-<project>
    # Strategy: find the last "container" directory and take everything after it.
    parts = stripped.split("-")
    containers = {"Sites", "Projects", "Documents", "repos", "src", "code",
                  "dev", "home", "Home", "work", "workspace", "Desktop",
                  "AndroidStudioProjects", "IdeaProjects"}
    last_container = -1
    for i, p in enumerate(parts):
        if p in containers:
            last_container = i
    if last_container >= 0 and last_container < len(parts) - 1:
        return "-".join(parts[last_container + 1:])
    # Fallback: skip Users-<username> prefix (first 2 segments)
    if len(parts) > 2 and parts[0] == "Users":
        return "-".join(parts[2:])
    return stripped


def list_projects(claude_dir):
    """Print all projects with session counts and pretty names."""
    projects = find_projects(claude_dir)
    if not projects:
        print("No projects found in ~/.claude/projects/")
        return

    print()
    print(f"  {'Project':<35} {'Sessions':>8}")
    print(f"  {'─' * 35} {'─' * 8}")
    total_sessions = 0
    for proj in projects:
        sessions = find_session_files(proj)
        name = pretty_project_name(proj.name)
        total_sessions += len(sessions)
        print(f"  {name:<35} {len(sessions):>8}")
    print(f"  {'─' * 35} {'─' * 8}")
    print(f"  {'Total':<35} {total_sessions:>8}")
    print()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _detect_cwd_project(projects):
    """Find the project matching the current working directory.

    Claude Code encodes project paths by replacing ``/`` with ``-``:
    ``/Users/jdoe/Sites/my-project`` -> ``-Users-jdoe-Sites-my-project``

    We encode the CWD the same way and match against project dir names.
    """
    try:
        cwd = str(Path.cwd().resolve())
    except OSError:
        return None
    # Encode CWD the same way Claude Code does: replace / with -
    cwd_encoded = cwd.replace("/", "-")
    for p in projects:
        if p.name == cwd_encoded:
            return p
    # Also try parent directories (user might be in a subdirectory)
    parts = cwd.split("/")
    for i in range(len(parts) - 1, 1, -1):
        parent = "/".join(parts[:i])
        parent_encoded = parent.replace("/", "-")
        for p in projects:
            if p.name == parent_encoded:
                return p
    return None


# ---------------------------------------------------------------------------
# API integration — call seedcraft.dev for 500K seed matching
# ---------------------------------------------------------------------------

SEEDCRAFT_API_URL = "https://seedcraft.dev/api/generate"
SEEDCRAFT_TIMEOUT = 5  # seconds

def _build_api_stats(stats):
    """Build the stats payload for the SeedCraft API from merged stats."""
    return {
        "messages": stats["messages"],
        "tool_calls": stats["tool_calls"],
        "write_calls": stats["write_calls"],
        "total_active_hours": stats["total_active_ms"] / 3_600_000,
        "unique_tools": len(stats["tools_used"]),
        "agent_calls": stats["agent_calls"],
        "orchestrate_calls": stats["orchestrate_calls"],
        "project_count": stats["project_count"],
    }


def try_api_generate(stats, mode="curated"):
    """Try to generate a seed via the SeedCraft API (500K seeds).

    Returns the API response dict on success, or None on failure.
    Falls back silently so the local DB can be used instead.
    """
    try:
        import urllib.request
        payload = json.dumps({
            "mode": mode,
            "stats": _build_api_stats(stats),
        }).encode("utf-8")

        req = urllib.request.Request(
            SEEDCRAFT_API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=SEEDCRAFT_TIMEOUT) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass  # Network error, timeout, API down — fall back to local
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Convert Claude Code stats into a Minecraft world seed.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="All projects combined")
    group.add_argument("--project", type=str, help="Specific project (fuzzy match)")
    group.add_argument("--list", action="store_true", help="List all projects")
    parser.add_argument("--stats-only", action="store_true",
                       help="Show climate profile and stats without seed selection")
    parser.add_argument("--unique", action="store_true",
                       help="Generate a unique seed by hashing all stats (no DB lookup, biome unknown)")
    parser.add_argument("--db", type=str, help="Path to seeds_db.json (overrides default)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    claude_dir = find_claude_dir()

    # --list mode
    if args.list:
        list_projects(claude_dir)
        return

    projects = find_projects(claude_dir)

    if not projects:
        print("Error: no projects found in ~/.claude/projects/", file=sys.stderr)
        sys.exit(1)

    # Determine target: --project > --all > auto-detect CWD > fallback to all
    if args.project:
        search = args.project.lower().replace(" ", "").replace("-", "").replace("_", "")
        matched = []
        for p in projects:
            raw_norm = p.name.lower().replace("-", "").replace("_", "")
            pretty_norm = pretty_project_name(p.name).lower().replace("-", "").replace("_", "")
            if not raw_norm:
                continue
            if (search in raw_norm
                    or (len(raw_norm) > 2 and raw_norm in search)
                    or search in pretty_norm):
                matched.append(p)
        if not matched:
            print(f"Error: no project matching '{args.project}'.", file=sys.stderr)
            print("Available (use --list for details):", file=sys.stderr)
            for p in projects:
                print(f"  - {pretty_project_name(p.name)}", file=sys.stderr)
            sys.exit(1)
        target_projects = matched
        if len(matched) == 1:
            mode_label = f"project: {pretty_project_name(matched[0].name)}"
        else:
            mode_label = f"{len(matched)} projects matching '{args.project}'"
    elif args.all:
        target_projects = projects
        mode_label = "all projects"
    else:
        # Auto-detect: match current working directory to a project
        cwd_project = _detect_cwd_project(projects)
        if cwd_project:
            target_projects = [cwd_project]
            mode_label = f"project: {pretty_project_name(cwd_project.name)}"
        else:
            target_projects = projects
            mode_label = "all projects"

    # Collect stats
    all_stats = []
    project_names = []
    session_count = 0
    per_session_durations = []

    for proj_dir in target_projects:
        session_files = find_session_files(proj_dir)
        if not session_files:
            continue
        project_names.append(pretty_project_name(proj_dir.name))
        for sf in session_files:
            file_stats = parse_session_file(sf)
            if file_stats["messages"] > 0:
                all_stats.append(file_stats)
                session_count += 1
                # Compute active time per-file with gap detection
                # (avoids cross-session interleaving from merged timestamps)
                epochs = sorted(filter(None, (_ts_to_epoch_ms(t) for t in file_stats["timestamps"])))
                per_session_durations.extend(_detect_active_segments(epochs))

    if not all_stats:
        print("Error: no session data found.", file=sys.stderr)
        sys.exit(1)

    # Merge & derive
    merged = merge_stats(all_stats)
    compute_derived_stats(merged, session_count, len(project_names), project_names,
                          per_session_durations)

    # Climate profile
    profile = compute_climate_profile(merged)

    # --stats-only mode
    if args.stats_only:
        if args.json:
            print(json.dumps({
                "mode": mode_label,
                "profile": profile,
                "stats": _serializable_stats(merged),
            }, indent=2))
        else:
            render_stats_only(profile, merged, mode_label)
        return

    # --unique mode: hash stats directly into a seed (no DB lookup)
    if args.unique:
        # Try API first (consistent with curated mode)
        api_result = try_api_generate(merged, mode="unique")
        if api_result:
            seed = api_result["seed"]
        else:
            seed = generate_unique_seed(merged)
        compat = "Java & Bedrock" if _is_bedrock_safe(seed) else "Java only"
        share_text, tweet_url, gallery_url = _make_share_card(seed, "UNIQUE", merged, unique=True)
        if args.json:
            print(json.dumps({
                "seed": seed,
                "spawn_biome": "unknown (discover it!)",
                "spawn_x": "?",
                "spawn_z": "?",
                "compatibility": compat,
                "chunkbase_url": f"https://www.chunkbase.com/apps/seed-map#{seed}",
                "share_text": share_text,
                "tweet_url": tweet_url,
                "gallery_url": gallery_url,
                "mode": mode_label + " [unique]",
                "stats": _serializable_stats(merged),
                "unique": True,
            }, indent=2))
        else:
            print()
            print(f"  Unique Seed: {seed}  [{compat}]")
            print()
            print(f"  Generated by hashing all your Claude Code stats.")
            print(f"  This seed is 100% unique to your exact usage.")
            print(f"  Biome: discover it in Minecraft or on Chunkbase!")
            print()
            print(f"  Preview: https://www.chunkbase.com/apps/seed-map#{seed}")
            print()
            print(f"  {share_text}")
            print()
        return

    # Default: biome-matched seed selection
    # Try API first (500K seeds, better matching)
    api_result = try_api_generate(merged, mode="curated")

    if api_result and "seed" in api_result and "spawn_biome" in api_result:
        # API succeeded — use its result (500K seed DB)
        seed_entry = {
            "seed": api_result["seed"],
            "spawn_biome": api_result["spawn_biome"],
            "spawn_x": api_result.get("spawn_x", 0),
            "spawn_z": api_result.get("spawn_z", 0),
            "climate": api_result.get("profile", profile),
            "biome_diversity": 0,
        }
        # Use API profile if available
        if "profile" in api_result:
            profile.update({
                k: api_result["profile"][k]
                for k in api_result["profile"]
                if k in profile
            })
    else:
        # API failed — fall back to local DB (7K seeds)
        db_path = Path(args.db) if args.db else None
        seeds_db = load_seed_database(db_path)
        seed_entry = select_seed(profile, seeds_db, merged)

    # Output
    seed = seed_entry["seed"]
    compat = "Java & Bedrock" if _is_bedrock_safe(seed) else "Java only"
    biome_display = BIOME_LABELS.get(seed_entry["spawn_biome"],
                                      seed_entry["spawn_biome"].upper().replace("_", " "))
    share_text, tweet_url, gallery_url = _make_share_card(seed, biome_display, merged, profile)
    if args.json:
        print(json.dumps({
            "seed": seed,
            "spawn_biome": seed_entry["spawn_biome"],
            "spawn_biome_display": biome_display,
            "spawn_x": seed_entry.get("spawn_x", 0),
            "spawn_z": seed_entry.get("spawn_z", 0),
            "compatibility": compat,
            "chunkbase_url": f"https://www.chunkbase.com/apps/seed-map#{seed}",
            "share_text": share_text,
            "tweet_url": tweet_url,
            "gallery_url": gallery_url,
            "profile": profile,
            "stats": _serializable_stats(merged),
            "mode": mode_label,
        }, indent=2))
    else:
        render_output(seed_entry, profile, merged, mode_label)


if __name__ == "__main__":
    main()
