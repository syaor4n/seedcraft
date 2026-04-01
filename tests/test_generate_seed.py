#!/usr/bin/env python3
"""Tests for the Claude Code -> Minecraft Seed generator."""

import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_seed as gs

# ---------------------------------------------------------------------------
# Fixtures — realistic Claude Code JSONL session data
# ---------------------------------------------------------------------------

FIXTURE_USER_MSG = json.dumps({
    "parentUuid": "root",
    "isSidechain": False,
    "type": "user",
    "message": {
        "role": "user",
        "content": "Fix the login bug in auth.py"
    },
    "uuid": "aaa-111",
    "timestamp": 1711234560000,
    "userType": "external",
    "sessionId": "sess-1",
    "version": "1.0",
})

FIXTURE_ASSISTANT_MSG = json.dumps({
    "parentUuid": "aaa-111",
    "isSidechain": False,
    "type": "assistant",
    "message": {
        "role": "assistant",
        "model": "claude-opus-4-6",
        "content": [
            {"type": "thinking", "thinking": "Let me look at auth.py"},
            {"type": "text", "text": "I'll read the auth file first."},
            {"type": "tool_use", "id": "tu-1", "name": "Read",
             "input": {"file_path": "/app/auth.py"}},
        ]
    },
    "uuid": "bbb-222",
    "timestamp": 1711234565000,
    "sessionId": "sess-1",
    "version": "1.0",
})

FIXTURE_USER_TOOL_RESULT = json.dumps({
    "parentUuid": "bbb-222",
    "isSidechain": False,
    "type": "user",
    "message": {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "tu-1",
             "content": "def login():\n    pass"},
        ]
    },
    "uuid": "ccc-333",
    "timestamp": 1711234567000,
    "sessionId": "sess-1",
    "version": "1.0",
})

FIXTURE_ASSISTANT_EDIT = json.dumps({
    "parentUuid": "ccc-333",
    "isSidechain": False,
    "type": "assistant",
    "message": {
        "role": "assistant",
        "model": "claude-opus-4-6",
        "content": [
            {"type": "text", "text": "Found the bug. Fixing now."},
            {"type": "tool_use", "id": "tu-2", "name": "Edit",
             "input": {"file_path": "/app/auth.py", "old_string": "pass",
                        "new_string": "return True"}},
        ]
    },
    "uuid": "ddd-444",
    "timestamp": 1711234570000,
    "sessionId": "sess-1",
    "version": "1.0",
})

FIXTURE_USER_ERROR_RESULT = json.dumps({
    "parentUuid": "ddd-444",
    "isSidechain": False,
    "type": "user",
    "message": {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "tu-2",
             "is_error": True,
             "content": "Error: old_string not found in file"},
        ]
    },
    "uuid": "eee-555",
    "timestamp": 1711234572000,
    "sessionId": "sess-1",
    "version": "1.0",
})

FIXTURE_SYSTEM_MSG = json.dumps({
    "parentUuid": "eee-555",
    "type": "system",
    "subtype": "completion",
    "durationMs": 12000,
    "timestamp": 1711234580000,
    "sessionId": "sess-1",
})

FIXTURE_PROGRESS_MSG = json.dumps({
    "type": "progress",
    "data": {"tool": "Read", "status": "running"},
    "timestamp": 1711234563000,
    "sessionId": "sess-1",
})

ALL_FIXTURE_LINES = [
    FIXTURE_USER_MSG,
    FIXTURE_ASSISTANT_MSG,
    FIXTURE_USER_TOOL_RESULT,
    FIXTURE_ASSISTANT_EDIT,
    FIXTURE_USER_ERROR_RESULT,
    FIXTURE_SYSTEM_MSG,
    FIXTURE_PROGRESS_MSG,
]


def write_session_file(tmpdir, lines):
    """Write lines to a temporary JSONL file and return its path."""
    fp = Path(tmpdir) / "test-session.jsonl"
    fp.write_text("\n".join(lines) + "\n")
    return fp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParser(unittest.TestCase):
    """Test JSONL parsing with realistic Claude Code format."""

    def test_parse_counts_messages(self):
        with tempfile.TemporaryDirectory() as td:
            fp = write_session_file(td, ALL_FIXTURE_LINES)
            stats = gs.parse_session_file(fp)
        # 2 user messages + 1 tool result user + 1 error user = 3 user
        # Wait: type=user entries are: FIXTURE_USER_MSG, FIXTURE_USER_TOOL_RESULT,
        # FIXTURE_USER_ERROR_RESULT = 3 human messages
        self.assertEqual(stats["human_messages"], 3)
        # 2 assistant messages
        self.assertEqual(stats["assistant_messages"], 2)
        self.assertEqual(stats["messages"], 5)

    def test_parse_counts_tool_calls(self):
        with tempfile.TemporaryDirectory() as td:
            fp = write_session_file(td, ALL_FIXTURE_LINES)
            stats = gs.parse_session_file(fp)
        # Read + Edit = 2 tool_use blocks
        self.assertEqual(stats["tool_calls"], 2)
        self.assertIn("Read", stats["tools_used"])
        self.assertIn("Edit", stats["tools_used"])
        self.assertEqual(stats["tool_calls_by_name"]["Read"], 1)
        self.assertEqual(stats["tool_calls_by_name"]["Edit"], 1)

    def test_parse_counts_errors(self):
        with tempfile.TemporaryDirectory() as td:
            fp = write_session_file(td, ALL_FIXTURE_LINES)
            stats = gs.parse_session_file(fp)
        self.assertEqual(stats["error_count"], 1)

    def test_parse_extracts_timestamps(self):
        with tempfile.TemporaryDirectory() as td:
            fp = write_session_file(td, ALL_FIXTURE_LINES)
            stats = gs.parse_session_file(fp)
        # All 7 lines have timestamps
        self.assertEqual(len(stats["timestamps"]), 7)
        self.assertIn(1711234560000, stats["timestamps"])

    def test_parse_extracts_model(self):
        with tempfile.TemporaryDirectory() as td:
            fp = write_session_file(td, ALL_FIXTURE_LINES)
            stats = gs.parse_session_file(fp)
        self.assertEqual(stats["models_used"]["claude-opus-4-6"], 2)

    def test_parse_counts_chars(self):
        with tempfile.TemporaryDirectory() as td:
            fp = write_session_file(td, ALL_FIXTURE_LINES)
            stats = gs.parse_session_file(fp)
        self.assertGreater(stats["total_chars"], 0)

    def test_parse_empty_file(self):
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "empty.jsonl"
            fp.write_text("")
            stats = gs.parse_session_file(fp)
        self.assertEqual(stats["messages"], 0)

    def test_parse_malformed_lines(self):
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "bad.jsonl"
            fp.write_text("not json\n{bad json}\n" + FIXTURE_USER_MSG + "\n")
            stats = gs.parse_session_file(fp)
        # Only the valid user message should be parsed
        self.assertEqual(stats["human_messages"], 1)


class TestMergeStats(unittest.TestCase):
    """Test merging multiple stat dicts."""

    def test_merge_sums(self):
        # Create two minimal stats
        a = {
            "messages": 10, "human_messages": 5, "assistant_messages": 5,
            "tool_calls": 3, "tool_calls_by_name": Counter({"Read": 2, "Edit": 1}),
            "tools_used": {"Read", "Edit"}, "total_chars": 1000,
            "timestamps": [100, 200], "models_used": Counter({"opus": 5}),
            "error_count": 1, "agent_calls": 0,
        }
        b = {
            "messages": 20, "human_messages": 8, "assistant_messages": 12,
            "tool_calls": 7, "tool_calls_by_name": Counter({"Bash": 5, "Read": 2}),
            "tools_used": {"Bash", "Read"}, "total_chars": 2000,
            "timestamps": [300, 400], "models_used": Counter({"opus": 12}),
            "error_count": 0, "agent_calls": 2,
        }
        m = gs.merge_stats([a, b])
        self.assertEqual(m["messages"], 30)
        self.assertEqual(m["tool_calls"], 10)
        self.assertEqual(m["tools_used"], {"Read", "Edit", "Bash"})
        self.assertEqual(m["tool_calls_by_name"]["Read"], 4)
        self.assertEqual(m["timestamps"], [100, 200, 300, 400])
        self.assertEqual(m["agent_calls"], 2)


class TestNormalize(unittest.TestCase):
    """Test piecewise linear normalization."""

    def test_below_min(self):
        bp = [(0, 0.0), (100, 1.0)]
        self.assertAlmostEqual(gs.normalize(-10, bp), 0.0)

    def test_above_max(self):
        bp = [(0, 0.0), (100, 1.0)]
        self.assertAlmostEqual(gs.normalize(200, bp), 1.0)

    def test_exact_breakpoint(self):
        bp = [(0, 0.0), (50, 0.5), (100, 1.0)]
        self.assertAlmostEqual(gs.normalize(50, bp), 0.5)

    def test_midpoint_interpolation(self):
        bp = [(0, 0.0), (100, 1.0)]
        self.assertAlmostEqual(gs.normalize(50, bp), 0.5)

    def test_multi_segment(self):
        bp = [(0, 0.0), (10, 0.2), (100, 1.0)]
        self.assertAlmostEqual(gs.normalize(5, bp), 0.1)
        self.assertAlmostEqual(gs.normalize(55, bp), 0.6)


class TestClimateProfile(unittest.TestCase):
    """Test stats-to-climate mapping produces valid profiles."""

    def _make_stats(self, **overrides):
        base = {
            "messages": 10000,
            "human_messages": 4000,
            "assistant_messages": 6000,
            "tool_calls": 5000,
            "tool_calls_by_name": Counter({"Read": 2000, "Edit": 1500,
                                            "Bash": 1000, "Grep": 500}),
            "tools_used": {"Read", "Edit", "Bash", "Grep", "Write", "Glob"},
            "total_chars": 500000,
            "timestamps": [],
            "models_used": Counter({"claude-opus-4-6": 6000}),
            "error_count": 50,
            "agent_calls": 30,
            "session_count": 10,
            "project_count": 5,
            "project_names": ["proj-a", "proj-b", "proj-c", "proj-d", "proj-e"],
            "total_duration_ms": 10 * 3600 * 1000,
            "total_active_ms": 8 * 3600 * 1000,
            "avg_session_duration_ms": 3600 * 1000,
            "session_durations": [3600000] * 8,
            "hour_distribution": [0] * 24,
            "night_ratio": 0.0,
            "read_calls": 2500,
            "write_calls": 1500,
            "execute_calls": 1000,
            "orchestrate_calls": 30,
            "mcp_calls": 0,
            "write_ratio": 0.375,
            "tools_per_message": 0.5,
            "error_rate": 0.01,
        }
        base.update(overrides)
        return base

    def test_profile_values_in_range(self):
        stats = self._make_stats()
        profile = gs.compute_climate_profile(stats)
        for key, val in profile.items():
            self.assertGreaterEqual(val, 0.0, f"{key} below 0")
            self.assertLessEqual(val, 1.0, f"{key} above 1")

    def test_more_messages_higher_temperature(self):
        low = self._make_stats(messages=100)
        high = self._make_stats(messages=100000)
        p_low = gs.compute_climate_profile(low)
        p_high = gs.compute_climate_profile(high)
        self.assertGreater(p_high["temperature"], p_low["temperature"])

    def test_more_tool_calls_higher_humidity(self):
        low = self._make_stats(tool_calls=50)
        high = self._make_stats(tool_calls=30000)
        p_low = gs.compute_climate_profile(low)
        p_high = gs.compute_climate_profile(high)
        self.assertGreater(p_high["humidity"], p_low["humidity"])

    def test_more_active_time_lower_erosion(self):
        low = self._make_stats(total_active_ms=1 * 3600 * 1000)  # 1 hour
        high = self._make_stats(total_active_ms=100 * 3600 * 1000)  # 100 hours
        p_low = gs.compute_climate_profile(low)
        p_high = gs.compute_climate_profile(high)
        # Lower erosion = taller mountains
        self.assertLess(p_high["erosion"], p_low["erosion"])

    def test_more_projects_higher_diversity(self):
        low = self._make_stats(project_count=1)
        high = self._make_stats(project_count=20)
        p_low = gs.compute_climate_profile(low)
        p_high = gs.compute_climate_profile(high)
        self.assertGreater(p_high["biome_diversity"], p_low["biome_diversity"])

    def test_more_writes_higher_continentalness(self):
        low = self._make_stats(write_calls=10)
        high = self._make_stats(write_calls=8000)
        p_low = gs.compute_climate_profile(low)
        p_high = gs.compute_climate_profile(high)
        self.assertGreater(p_high["continentalness"], p_low["continentalness"])


class TestSeedSelection(unittest.TestCase):
    """Test seed selection logic."""

    MOCK_SEEDS = [
        {"seed": 111, "spawn_biome": "desert",
         "climate": {"temperature": 0.9, "humidity": 0.1,
                     "continentalness": 0.7, "erosion": 0.8, "weirdness": 0.3},
         "biome_diversity": 3},
        {"seed": 222, "spawn_biome": "jungle",
         "climate": {"temperature": 0.9, "humidity": 0.9,
                     "continentalness": 0.6, "erosion": 0.5, "weirdness": 0.4},
         "biome_diversity": 8},
        {"seed": 333, "spawn_biome": "snowy_plains",
         "climate": {"temperature": 0.1, "humidity": 0.3,
                     "continentalness": 0.5, "erosion": 0.7, "weirdness": 0.2},
         "biome_diversity": 2},
        {"seed": 444, "spawn_biome": "plains",
         "climate": {"temperature": 0.5, "humidity": 0.5,
                     "continentalness": 0.5, "erosion": 0.5, "weirdness": 0.5},
         "biome_diversity": 5},
    ]

    def _make_stats(self):
        return {
            "messages": 1000, "tool_calls": 500,
            "tools_used": {"Read", "Edit"},
            "total_chars": 50000,
            "project_names": ["test"],
        }

    def test_selects_desert_biome_for_hot_dry(self):
        # Two-stage: profile is closest to desert CENTER, so biome must be desert
        profile = {
            "temperature": 0.85, "humidity": 0.15,
            "continentalness": 0.65, "erosion": 0.75, "weirdness": 0.25,
            "structure_density": 0.3, "biome_diversity": 0.3,
        }
        result = gs.select_seed(profile, self.MOCK_SEEDS, self._make_stats())
        self.assertEqual(result["spawn_biome"], "desert")

    def test_selects_snowy_biome_for_cold(self):
        profile = {
            "temperature": 0.12, "humidity": 0.25,
            "continentalness": 0.48, "erosion": 0.65, "weirdness": 0.18,
            "structure_density": 0.1, "biome_diversity": 0.1,
        }
        result = gs.select_seed(profile, self.MOCK_SEEDS, self._make_stats())
        self.assertEqual(result["spawn_biome"], "snowy_plains")

    def test_selects_jungle_for_hot_humid(self):
        profile = {
            "temperature": 0.88, "humidity": 0.85,
            "continentalness": 0.58, "erosion": 0.48, "weirdness": 0.38,
            "structure_density": 0.5, "biome_diversity": 0.5,
        }
        result = gs.select_seed(profile, self.MOCK_SEEDS, self._make_stats())
        self.assertEqual(result["spawn_biome"], "jungle")

    def test_deterministic(self):
        profile = {
            "temperature": 0.5, "humidity": 0.5,
            "continentalness": 0.5, "erosion": 0.5, "weirdness": 0.5,
            "structure_density": 0.5, "biome_diversity": 0.5,
        }
        stats = self._make_stats()
        r1 = gs.select_seed(profile, self.MOCK_SEEDS, stats)
        r2 = gs.select_seed(profile, self.MOCK_SEEDS, stats)
        self.assertEqual(r1["seed"], r2["seed"])

    def test_different_stats_can_differ(self):
        profile = {
            "temperature": 0.5, "humidity": 0.5,
            "continentalness": 0.5, "erosion": 0.5, "weirdness": 0.5,
            "structure_density": 0.5, "biome_diversity": 0.5,
        }
        stats_a = {"messages": 1000, "tool_calls": 500,
                    "tools_used": {"Read"}, "total_chars": 50000,
                    "project_names": ["a"]}
        stats_b = {"messages": 9999, "tool_calls": 9999,
                    "tools_used": {"Write"}, "total_chars": 99999,
                    "project_names": ["b"]}
        r_a = gs.select_seed(profile, self.MOCK_SEEDS, stats_a)
        r_b = gs.select_seed(profile, self.MOCK_SEEDS, stats_b)
        # They might differ — or not — depending on hash. Just ensure no crash.
        self.assertIn(r_a["seed"], [111, 222, 333, 444])
        self.assertIn(r_b["seed"], [111, 222, 333, 444])


class TestSeedDatabase(unittest.TestCase):
    """Test the actual seeds_db.json is valid."""

    def test_db_loads(self):
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")
        seeds = gs.load_seed_database(db_path)
        self.assertGreater(len(seeds), 100)

    def test_db_seeds_have_required_fields(self):
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")
        seeds = gs.load_seed_database(db_path)
        for s in seeds[:20]:  # spot check
            self.assertIn("seed", s)
            self.assertIn("spawn_biome", s)
            self.assertIn("climate", s)
            c = s["climate"]
            for k in ["temperature", "humidity", "continentalness", "erosion", "weirdness"]:
                self.assertIn(k, c)
                self.assertGreaterEqual(c[k], 0.0)
                self.assertLessEqual(c[k], 1.0)

    def test_db_has_biome_diversity(self):
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")
        seeds = gs.load_seed_database(db_path)
        biomes = set(s["spawn_biome"] for s in seeds)
        # Should have at least 20 unique biomes
        self.assertGreaterEqual(len(biomes), 20)


class TestClimateLabels(unittest.TestCase):

    def test_cold_temperature(self):
        self.assertEqual(gs.climate_label("temperature", 0.05), "Frozen")

    def test_hot_temperature(self):
        self.assertEqual(gs.climate_label("temperature", 0.95), "Scorching")

    def test_mid_humidity(self):
        label = gs.climate_label("humidity", 0.50)
        self.assertIn(label, ["Moderate", "Humid"])


class TestOutputRendering(unittest.TestCase):
    """Smoke test that rendering doesn't crash."""

    def test_render_does_not_crash(self):
        seed_entry = {
            "seed": -123456789,
            "spawn_biome": "jungle",
            "climate": {"temperature": 0.8, "humidity": 0.9,
                        "continentalness": 0.6, "erosion": 0.4, "weirdness": 0.5},
            "biome_diversity": 8,
        }
        profile = {
            "temperature": 0.8, "humidity": 0.9, "continentalness": 0.6,
            "erosion": 0.4, "weirdness": 0.5, "structure_density": 0.3,
            "biome_diversity": 0.7,
        }
        stats = {
            "messages": 10000, "human_messages": 4000,
            "assistant_messages": 6000, "tool_calls": 5000,
            "tools_used": {"Read", "Edit", "Bash"},
            "tool_calls_by_name": Counter({"Read": 2000}),
            "total_chars": 100000, "timestamps": [],
            "models_used": Counter({"claude-opus-4-6": 100}),
            "error_count": 5, "agent_calls": 10,
            "project_count": 3, "project_names": ["a", "b", "c"],
            "session_count": 5,
            "total_active_ms": 36000000,
            "avg_session_duration_ms": 3600000,
            "tools_per_message": 0.5,
            "read_calls": 2000, "write_calls": 1000,
            "error_rate": 0.001,
            "orchestrate_calls": 10,
        }
        # Just ensure it doesn't raise
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            gs.render_output(seed_entry, profile, stats, "test")
        output = buf.getvalue()
        self.assertIn("-123456789", output)
        self.assertIn("JUNGLE", output)


class TestTimestampConversion(unittest.TestCase):
    """Test _ts_to_epoch_ms with all timestamp formats."""

    def test_iso8601_with_z(self):
        ms = gs._ts_to_epoch_ms("2026-03-13T10:46:21.187Z")
        self.assertIsNotNone(ms)
        self.assertIsInstance(ms, int)
        # Should be around March 2026
        self.assertGreater(ms, 1700000000000)

    def test_iso8601_with_offset(self):
        ms = gs._ts_to_epoch_ms("2026-03-13T10:46:21.187+02:00")
        self.assertIsNotNone(ms)

    def test_iso8601_no_tz(self):
        ms = gs._ts_to_epoch_ms("2026-03-13T10:46:21")
        self.assertIsNotNone(ms)

    def test_epoch_ms_int(self):
        ms = gs._ts_to_epoch_ms(1711234560000)
        self.assertEqual(ms, 1711234560000)

    def test_epoch_seconds_float(self):
        ms = gs._ts_to_epoch_ms(1711234560.5)
        self.assertEqual(ms, 1711234560500)

    def test_none_returns_none(self):
        self.assertIsNone(gs._ts_to_epoch_ms(None))

    def test_garbage_string_returns_none(self):
        self.assertIsNone(gs._ts_to_epoch_ms("not-a-date"))

    def test_empty_string_returns_none(self):
        self.assertIsNone(gs._ts_to_epoch_ms(""))


class TestDerivedStats(unittest.TestCase):
    """Test compute_derived_stats with various timestamp formats."""

    def test_iso_timestamps(self):
        stats = {
            "messages": 10, "human_messages": 5, "assistant_messages": 5,
            "tool_calls": 3, "tool_calls_by_name": Counter({"Read": 2, "Edit": 1}),
            "tools_used": {"Read", "Edit"}, "total_chars": 1000,
            "timestamps": [
                "2026-03-13T10:00:00.000Z",
                "2026-03-13T10:30:00.000Z",
                "2026-03-13T11:00:00.000Z",
            ],
            "models_used": Counter({"opus": 5}),
            "error_count": 0, "agent_calls": 0,
        }
        gs.compute_derived_stats(stats, 1, 1, ["test-project"])
        # 1 hour total
        self.assertAlmostEqual(stats["total_duration_ms"], 3600000, delta=1000)
        self.assertEqual(stats["project_count"], 1)
        self.assertGreater(stats["total_active_ms"], 0)

    def test_single_timestamp(self):
        stats = {
            "messages": 1, "human_messages": 1, "assistant_messages": 0,
            "tool_calls": 0, "tool_calls_by_name": Counter(),
            "tools_used": set(), "total_chars": 10,
            "timestamps": ["2026-03-13T10:00:00.000Z"],
            "models_used": Counter(), "error_count": 0, "agent_calls": 0,
        }
        gs.compute_derived_stats(stats, 1, 1, ["test"])
        self.assertEqual(stats["total_duration_ms"], 0)
        self.assertEqual(stats["total_active_ms"], 0)

    def test_no_timestamps(self):
        stats = {
            "messages": 5, "human_messages": 2, "assistant_messages": 3,
            "tool_calls": 1, "tool_calls_by_name": Counter({"Bash": 1}),
            "tools_used": {"Bash"}, "total_chars": 100,
            "timestamps": [],
            "models_used": Counter(), "error_count": 0, "agent_calls": 0,
        }
        gs.compute_derived_stats(stats, 1, 1, ["test"])
        self.assertEqual(stats["total_duration_ms"], 0)
        self.assertEqual(stats["tools_per_message"], 0.2)

    def test_ratios_computed(self):
        stats = {
            "messages": 100, "human_messages": 40, "assistant_messages": 60,
            "tool_calls": 50, "tool_calls_by_name": Counter({
                "Read": 20, "Edit": 10, "Bash": 15, "Grep": 5,
            }),
            "tools_used": {"Read", "Edit", "Bash", "Grep"}, "total_chars": 5000,
            "timestamps": [],
            "models_used": Counter(), "error_count": 3, "agent_calls": 2,
        }
        gs.compute_derived_stats(stats, 1, 2, ["a", "b"])
        self.assertAlmostEqual(stats["tools_per_message"], 0.5)
        self.assertEqual(stats["read_calls"], 25)  # Read=20 + Grep=5
        self.assertEqual(stats["write_calls"], 10)  # Edit=10
        self.assertEqual(stats["execute_calls"], 15)  # Bash=15
        self.assertAlmostEqual(stats["write_ratio"], 10 / 35)  # 10/(25+10)
        self.assertAlmostEqual(stats["error_rate"], 3 / 50)


class TestPrettyProjectName(unittest.TestCase):

    def test_standard_sites_path(self):
        self.assertEqual(
            gs.pretty_project_name("-Users-jdoe-Sites-my-project"),
            "my-project",
        )

    def test_android_studio(self):
        self.assertEqual(
            gs.pretty_project_name("-Users-jdoe-AndroidStudioProjects-MyApp"),
            "MyApp",
        )

    def test_root_dash(self):
        self.assertEqual(gs.pretty_project_name("-"), "(root)")

    def test_simple_name(self):
        name = gs.pretty_project_name("my-project")
        self.assertEqual(name, "my-project")

    def test_deep_path(self):
        name = gs.pretty_project_name("-Users-jdoe-Sites-claude-seed-generator")
        self.assertEqual(name, "claude-seed-generator")


class TestNarrativeCoverage(unittest.TestCase):
    """Ensure every biome in the DB has a working narrative."""

    def test_all_db_biomes_have_narrative(self):
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")
        seeds = gs.load_seed_database(db_path)
        biomes = set(s["spawn_biome"] for s in seeds)

        test_stats = {
            "messages": 5000, "tool_calls": 2000,
            "tools_used": {"Read", "Edit", "Bash"},
            "tools_per_message": 0.4, "project_count": 5,
            "total_active_ms": 36000000, "avg_session_duration_ms": 3600000,
            "read_calls": 1500, "write_calls": 800,
        }
        for biome in biomes:
            try:
                result = gs.get_narrative(biome, test_stats)
                self.assertIsInstance(result, str)
                self.assertGreater(len(result), 10)
            except (KeyError, IndexError) as e:
                self.fail(f"Narrative for '{biome}' crashed: {e}")

    def test_all_db_biomes_have_label(self):
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")
        seeds = gs.load_seed_database(db_path)
        biomes = set(s["spawn_biome"] for s in seeds)
        for biome in biomes:
            label = gs.BIOME_LABELS.get(biome, biome.upper().replace("_", " "))
            self.assertIsInstance(label, str)
            self.assertGreater(len(label), 0)


class TestParserISOTimestamps(unittest.TestCase):
    """Test parser with ISO-8601 timestamps (real Claude Code format)."""

    def test_iso_timestamps_collected(self):
        msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": "hello"},
            "timestamp": "2026-03-13T10:46:21.187Z",
            "uuid": "x",
        })
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "iso.jsonl"
            fp.write_text(msg + "\n")
            stats = gs.parse_session_file(fp)
        self.assertEqual(len(stats["timestamps"]), 1)
        self.assertEqual(stats["timestamps"][0], "2026-03-13T10:46:21.187Z")


class TestWrapLines(unittest.TestCase):

    def test_empty_text(self):
        lines = []
        gs._wrap_lines("", lines, 50)
        self.assertEqual(len(lines), 0)

    def test_short_text(self):
        lines = []
        gs._wrap_lines("Hello world", lines, 50)
        self.assertEqual(len(lines), 1)

    def test_long_text_wraps(self):
        lines = []
        text = "This is a sentence that is definitely longer than twenty characters and should wrap"
        gs._wrap_lines(text, lines, 30)
        self.assertGreater(len(lines), 1)


class TestSelectSeedEdgeCases(unittest.TestCase):

    def _profile(self):
        return {"temperature": 0.5, "humidity": 0.5, "continentalness": 0.5,
                "erosion": 0.5, "weirdness": 0.5, "structure_density": 0.5,
                "biome_diversity": 0.5}

    def _stats(self):
        return {"messages": 1, "tool_calls": 0, "tools_used": set(),
                "total_chars": 10, "project_names": ["x"]}

    def test_empty_seed_db(self):
        """Empty DB must not crash (was ZeroDivisionError)."""
        result = gs.select_seed(self._profile(), [], self._stats())
        self.assertEqual(result["spawn_biome"], "plains")
        self.assertEqual(result["seed"], 0)

    def test_single_seed_db(self):
        db = [{"seed": 42, "spawn_biome": "desert",
               "climate": {"temperature": 0.9, "humidity": 0.1,
                           "continentalness": 0.7, "erosion": 0.8, "weirdness": 0.3},
               "biome_diversity": 2}]
        result = gs.select_seed(self._profile(), db, self._stats())
        self.assertEqual(result["seed"], 42)


class TestBarEdgeCases(unittest.TestCase):

    def test_bar_zero(self):
        bar = gs._bar(0.0)
        self.assertNotIn("\u2588", bar)  # no filled blocks

    def test_bar_one(self):
        bar = gs._bar(1.0)
        self.assertNotIn("\u2591", bar)  # no empty blocks

    def test_bar_length(self):
        for v in [0.0, 0.25, 0.5, 0.75, 1.0]:
            bar = gs._bar(v, width=12)
            self.assertEqual(len(bar), 12)


class TestClimateMonotonicity(unittest.TestCase):
    """Verify all climate parameters are monotonic w.r.t. their stat."""

    def _make(self, **kw):
        base = {
            "messages": 10000, "tool_calls": 5000,
            "write_calls": 1500,
            "total_active_ms": 10 * 3600000,
            "tools_used": {"Read", "Edit", "Bash", "Grep", "Write"},
            "agent_calls": 20, "orchestrate_calls": 10,
            "project_count": 5,
        }
        base.update(kw)
        return base

    def test_weirdness_increases_with_tool_diversity(self):
        low = self._make(tools_used={"Read", "Edit"})
        high = self._make(tools_used=set(f"tool_{i}" for i in range(80)))
        self.assertGreater(
            gs.compute_climate_profile(high)["weirdness"],
            gs.compute_climate_profile(low)["weirdness"],
        )

    def test_structures_increase_with_agents(self):
        low = self._make(agent_calls=0, orchestrate_calls=0)
        high = self._make(agent_calls=500, orchestrate_calls=200)
        self.assertGreater(
            gs.compute_climate_profile(high)["structure_density"],
            gs.compute_climate_profile(low)["structure_density"],
        )


class TestPerFileDuration(unittest.TestCase):
    """Verify per-file durations are used when provided."""

    def test_per_file_overrides_gap_detection(self):
        stats = {
            "messages": 10, "human_messages": 5, "assistant_messages": 5,
            "tool_calls": 3, "tool_calls_by_name": Counter({"Read": 3}),
            "tools_used": {"Read"}, "total_chars": 1000,
            "timestamps": [
                "2026-03-13T10:00:00Z", "2026-03-13T11:00:00Z",
                "2026-03-13T10:30:00Z", "2026-03-13T11:30:00Z",
            ],
            "models_used": Counter(), "error_count": 0, "agent_calls": 0,
        }
        # Pre-computed per-file active segments (gap-detected per file)
        per_file = [1800000, 1800000]  # 2x 30 min active segments
        gs.compute_derived_stats(stats, 2, 1, ["test"], per_file)
        self.assertEqual(stats["total_active_ms"], 3600000)  # 1h total
        self.assertEqual(stats["avg_session_duration_ms"], 1800000)  # 30 min avg


class TestJsonOutput(unittest.TestCase):
    """Test _serializable_stats produces valid JSON."""

    def test_serializable(self):
        stats = {
            "messages": 100, "human_messages": 40, "assistant_messages": 60,
            "tool_calls": 50, "tool_calls_by_name": Counter({"Read": 30, "Edit": 20}),
            "tools_used": {"Read", "Edit"}, "total_chars": 5000,
            "project_count": 2, "project_names": ["a", "b"],
            "session_count": 3, "total_active_ms": 7200000,
            "avg_session_duration_ms": 2400000,
            "tools_per_message": 0.5, "write_ratio": 0.4, "error_rate": 0.01,
        }
        result = gs._serializable_stats(stats)
        # Must be JSON-serializable (no sets, Counters, etc.)
        serialized = json.dumps(result)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["messages"], 100)
        self.assertEqual(len(parsed["top_tools"]), 2)


class TestDetectActiveSegments(unittest.TestCase):
    """Test the shared gap-detection function."""

    def test_empty_list(self):
        self.assertEqual(gs._detect_active_segments([]), [])

    def test_single_timestamp(self):
        self.assertEqual(gs._detect_active_segments([1000]), [])

    def test_continuous_session(self):
        # 3 timestamps all within 30 min of each other
        epochs = [0, 600_000, 1_200_000]  # 0, 10m, 20m
        result = gs._detect_active_segments(epochs)
        self.assertEqual(result, [1_200_000])  # 20 minutes

    def test_gap_splits_sessions(self):
        # Two clusters with a 1h gap
        epochs = [0, 60_000, 3_660_000, 3_720_000]  # 0, 1m, 61m, 62m
        result = gs._detect_active_segments(epochs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], 60_000)   # first cluster: 1 min
        self.assertEqual(result[1], 60_000)   # second cluster: 1 min

    def test_zero_length_segments_filtered(self):
        # Two timestamps exactly 31m apart — each cluster has only 1 timestamp
        epochs = [0, 31 * 60 * 1000]
        result = gs._detect_active_segments(epochs)
        # Both clusters are single-timestamp, so zero-length, both filtered
        self.assertEqual(result, [])


class TestClimateDistance(unittest.TestCase):

    def test_identical_profiles_zero(self):
        a = {"temperature": 0.5, "humidity": 0.5, "continentalness": 0.5,
             "erosion": 0.5, "weirdness": 0.5}
        self.assertAlmostEqual(gs._climate_distance(a, a), 0.0)

    def test_symmetric(self):
        a = {"temperature": 0.3, "humidity": 0.7, "continentalness": 0.5,
             "erosion": 0.5, "weirdness": 0.5}
        b = {"temperature": 0.8, "humidity": 0.2, "continentalness": 0.5,
             "erosion": 0.5, "weirdness": 0.5}
        self.assertAlmostEqual(gs._climate_distance(a, b), gs._climate_distance(b, a))


class TestFuzzClimateProfile(unittest.TestCase):
    """Random stats should never crash compute_climate_profile."""

    def test_random_stats_no_crash(self):
        import random
        rng = random.Random(42)
        for _ in range(100):
            stats = {
                "messages": rng.randint(0, 500000),
                "tool_calls": rng.randint(0, 200000),
                "write_calls": rng.randint(0, 30000),
                "total_active_ms": rng.randint(0, 500 * 3600000),
                "tools_used": set(f"t{i}" for i in range(rng.randint(0, 120))),
                "agent_calls": rng.randint(0, 3000),
                "orchestrate_calls": rng.randint(0, 3000),
                "project_count": rng.randint(1, 80),
            }
            profile = gs.compute_climate_profile(stats)
            for k, v in profile.items():
                self.assertGreaterEqual(v, 0.0, f"{k}={v} for {stats}")
                self.assertLessEqual(v, 1.0, f"{k}={v} for {stats}")


class TestTwoStageSelection(unittest.TestCase):
    """Verify the two-stage selection always returns a seed of the closest biome."""

    def test_biome_is_always_closest_center(self):
        """The selected seed's biome must be the biome whose center is closest."""
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")
        seeds = gs.load_seed_database(db_path)

        # A few diverse profiles
        profiles = [
            {"temperature": 0.88, "humidity": 0.70, "continentalness": 0.60,
             "erosion": 0.40, "weirdness": 0.50},  # hot humid
            {"temperature": 0.17, "humidity": 0.30, "continentalness": 0.50,
             "erosion": 0.70, "weirdness": 0.20},  # cold dry
            {"temperature": 0.50, "humidity": 0.50, "continentalness": 0.55,
             "erosion": 0.50, "weirdness": 0.45},  # balanced
        ]
        stats = {"messages": 1, "tool_calls": 0, "tools_used": set(),
                 "total_chars": 0, "project_names": ["x"]}

        from collections import defaultdict
        for profile in profiles:
            result = gs.select_seed(profile, seeds, stats)
            selected_biome = result["spawn_biome"]

            # Verify: compute biome centers, check selected_biome IS the closest
            biome_groups = defaultdict(list)
            for s in seeds:
                biome_groups[s["spawn_biome"]].append(s)
            best_biome = None
            best_dist = float("inf")
            for biome, entries in biome_groups.items():
                center = {}
                for k in gs.CLIMATE_WEIGHTS:
                    if k == "biome_diversity":
                        center[k] = sum(min(e.get("biome_diversity", 5) / 15.0, 1.0) for e in entries) / len(entries)
                    else:
                        center[k] = sum(e["climate"][k] for e in entries) / len(entries)
                d = gs._climate_distance(profile, center)
                if d < best_dist:
                    best_dist = d
                    best_biome = biome

            self.assertEqual(selected_biome, best_biome,
                             f"Profile {profile} selected {selected_biome} but closest center is {best_biome}")


class TestIntegration(unittest.TestCase):
    """Full pipeline: mock session files -> seed output."""

    def test_full_pipeline(self):
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")

        # Create mock session directory
        with tempfile.TemporaryDirectory() as td:
            proj_dir = Path(td)
            # Write a realistic session file
            lines = ALL_FIXTURE_LINES  # 5 messages, 2 tool calls
            fp = proj_dir / "sess1.jsonl"
            fp.write_text("\n".join(lines) + "\n")

            # Parse
            session_files = [fp]
            all_stats = []
            durations = []
            for sf in session_files:
                st = gs.parse_session_file(sf)
                if st["messages"] > 0:
                    all_stats.append(st)
                    epochs = sorted(filter(None, (gs._ts_to_epoch_ms(t) for t in st["timestamps"])))
                    durations.extend(gs._detect_active_segments(epochs))

            self.assertGreater(len(all_stats), 0)

            merged = gs.merge_stats(all_stats)
            gs.compute_derived_stats(merged, len(all_stats), 1, ["test"], durations)
            profile = gs.compute_climate_profile(merged)

            # Select seed
            seeds = gs.load_seed_database(db_path)
            entry = gs.select_seed(profile, seeds, merged)

            # Verify output is valid
            self.assertIn("seed", entry)
            self.assertIn("spawn_biome", entry)
            self.assertIsInstance(entry["seed"], (int, float))
            self.assertIn(entry["spawn_biome"], gs.BIOME_LABELS)


class TestStatsOnlyOutput(unittest.TestCase):
    """Smoke test for stats-only rendering."""

    def test_render_stats_only(self):
        import io
        from contextlib import redirect_stdout
        profile = {
            "temperature": 0.5, "humidity": 0.5, "continentalness": 0.5,
            "erosion": 0.5, "weirdness": 0.5, "structure_density": 0.5,
            "biome_diversity": 0.5,
        }
        stats = {
            "messages": 1000, "human_messages": 400, "assistant_messages": 600,
            "tool_calls": 500, "tools_used": {"Read", "Edit"},
            "tool_calls_by_name": Counter({"Read": 300, "Edit": 200}),
            "total_chars": 50000, "project_count": 2,
            "models_used": Counter({"opus": 600}),
            "total_active_ms": 3600000, "session_count": 5,
            "tools_per_message": 0.5, "read_calls": 300, "write_calls": 200,
            "error_rate": 0.01, "orchestrate_calls": 0,
            "avg_session_duration_ms": 720000,
        }
        buf = io.StringIO()
        with redirect_stdout(buf):
            gs.render_stats_only(profile, stats, "test")
        output = buf.getvalue()
        self.assertIn("Climate Profile", output)
        self.assertIn("1,000", output)


# ---------------------------------------------------------------------------
# New tests: filling all 33 identified gaps
# ---------------------------------------------------------------------------

class TestGenerateUniqueSeed(unittest.TestCase):
    """Test the --unique hash-based seed generation."""

    def _stats(self, **overrides):
        base = {
            "messages": 1000, "human_messages": 400, "assistant_messages": 600,
            "tool_calls": 500, "tool_calls_by_name": Counter({"Read": 300, "Edit": 200}),
            "tools_used": {"Read", "Edit"}, "total_chars": 50000,
            "timestamps": [], "models_used": Counter({"opus": 600}),
            "error_count": 5, "agent_calls": 10,
            "session_count": 3, "project_count": 1, "project_names": ["test"],
            "total_active_ms": 3600000, "avg_session_duration_ms": 1200000,
            "read_calls": 300, "write_calls": 200, "execute_calls": 0,
            "orchestrate_calls": 10, "mcp_calls": 0,
            "tools_per_message": 0.5, "write_ratio": 0.4, "error_rate": 0.01,
        }
        base.update(overrides)
        return base

    def test_deterministic(self):
        stats = self._stats()
        s1 = gs.generate_unique_seed(stats)
        s2 = gs.generate_unique_seed(stats)
        self.assertEqual(s1, s2)

    def test_different_stats_different_seed(self):
        a = self._stats(messages=1000)
        b = self._stats(messages=9999)
        self.assertNotEqual(gs.generate_unique_seed(a), gs.generate_unique_seed(b))

    def test_bedrock_safe(self):
        seed = gs.generate_unique_seed(self._stats())
        self.assertTrue(gs._is_bedrock_safe(seed))

    def test_returns_int(self):
        seed = gs.generate_unique_seed(self._stats())
        self.assertIsInstance(seed, int)

    def test_different_project_names_different_seed(self):
        a = self._stats(project_names=["alpha"])
        b = self._stats(project_names=["beta"])
        self.assertNotEqual(gs.generate_unique_seed(a), gs.generate_unique_seed(b))


class TestIsBedrockSafe(unittest.TestCase):

    def test_small_positive(self):
        self.assertTrue(gs._is_bedrock_safe(42))

    def test_small_negative(self):
        self.assertTrue(gs._is_bedrock_safe(-42))

    def test_max_32bit(self):
        self.assertTrue(gs._is_bedrock_safe(2147483647))

    def test_min_32bit(self):
        self.assertTrue(gs._is_bedrock_safe(-2147483648))

    def test_over_32bit(self):
        self.assertFalse(gs._is_bedrock_safe(2147483648))

    def test_under_32bit(self):
        self.assertFalse(gs._is_bedrock_safe(-2147483649))


class TestSelectSeedBedrockPreference(unittest.TestCase):
    """Verify select_seed prefers bedrock-safe seeds."""

    def test_prefers_bedrock(self):
        # Create a mock DB with both bedrock-safe and unsafe seeds for same biome
        mock_db = [
            {"seed": 9999999999, "spawn_biome": "plains",  # NOT bedrock safe
             "climate": {"temperature": 0.5, "humidity": 0.5,
                         "continentalness": 0.5, "erosion": 0.5, "weirdness": 0.5},
             "biome_diversity": 5},
            {"seed": 42, "spawn_biome": "plains",  # bedrock safe
             "climate": {"temperature": 0.5, "humidity": 0.5,
                         "continentalness": 0.5, "erosion": 0.5, "weirdness": 0.5},
             "biome_diversity": 5},
        ]
        profile = {"temperature": 0.5, "humidity": 0.5, "continentalness": 0.5,
                    "erosion": 0.5, "weirdness": 0.5}
        stats = {"messages": 1, "tool_calls": 0, "tools_used": set(),
                 "total_chars": 0, "project_names": ["x"]}
        result = gs.select_seed(profile, mock_db, stats)
        self.assertTrue(gs._is_bedrock_safe(result["seed"]))


class TestDetectCwdProject(unittest.TestCase):

    def _mock_projects(self):
        """Create mock project Path objects."""
        import types
        projects = []
        for name in ["-Users-jdoe-Sites-my-api", "-Users-jdoe-Sites-frontend", "-"]:
            p = types.SimpleNamespace(name=name)
            projects.append(p)
        return projects

    def test_exact_match(self):
        projects = self._mock_projects()
        # Mock Path.cwd to return /Users/jdoe/Sites/my-api
        import unittest.mock
        with unittest.mock.patch("pathlib.Path.cwd") as mock_cwd:
            mock_cwd.return_value = Path("/Users/jdoe/Sites/my-api")
            result = gs._detect_cwd_project(projects)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "-Users-jdoe-Sites-my-api")

    def test_no_match(self):
        projects = self._mock_projects()
        import unittest.mock
        with unittest.mock.patch("pathlib.Path.cwd") as mock_cwd:
            mock_cwd.return_value = Path("/some/random/path")
            result = gs._detect_cwd_project(projects)
        self.assertIsNone(result)

    def test_subdirectory_match(self):
        projects = self._mock_projects()
        import unittest.mock
        with unittest.mock.patch("pathlib.Path.cwd") as mock_cwd:
            mock_cwd.return_value = Path("/Users/jdoe/Sites/my-api/src/components")
            result = gs._detect_cwd_project(projects)
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "-Users-jdoe-Sites-my-api")


class TestMergeStatsEdgeCases(unittest.TestCase):

    def test_merge_empty_list(self):
        result = gs.merge_stats([])
        self.assertEqual(result["messages"], 0)
        self.assertEqual(result["tool_calls"], 0)
        self.assertEqual(result["tools_used"], set())

    def test_merge_single(self):
        single = {
            "messages": 10, "human_messages": 4, "assistant_messages": 6,
            "tool_calls": 3, "tool_calls_by_name": Counter({"Read": 3}),
            "tools_used": {"Read"}, "total_chars": 500,
            "timestamps": [1000], "models_used": Counter({"opus": 6}),
            "error_count": 0, "agent_calls": 0,
        }
        result = gs.merge_stats([single])
        self.assertEqual(result["messages"], 10)
        self.assertEqual(result["tool_calls"], 3)


class TestExtremeStats(unittest.TestCase):
    """Test with extreme stat values — zero, minimum, maximum."""

    def _make_derived(self, **overrides):
        stats = {
            "messages": 0, "human_messages": 0, "assistant_messages": 0,
            "tool_calls": 0, "tool_calls_by_name": Counter(),
            "tools_used": set(), "total_chars": 0,
            "timestamps": [], "models_used": Counter(),
            "error_count": 0, "agent_calls": 0,
        }
        stats.update(overrides)
        gs.compute_derived_stats(stats, 0, 0, [])
        return stats

    def test_zero_everything(self):
        stats = self._make_derived()
        profile = gs.compute_climate_profile(stats)
        for k, v in profile.items():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_million_messages(self):
        stats = self._make_derived(messages=1000000, tool_calls=500000,
                                    tools_used=set(f"t{i}" for i in range(100)))
        stats["write_calls"] = 100000
        stats["total_active_ms"] = 1000 * 3600000
        stats["agent_calls"] = 5000
        stats["orchestrate_calls"] = 5000
        stats["project_count"] = 50
        profile = gs.compute_climate_profile(stats)
        # Should be at or near maximum for temperature and humidity
        self.assertGreater(profile["temperature"], 0.90)
        self.assertGreater(profile["humidity"], 0.80)

    def test_single_message_session(self):
        stats = self._make_derived(
            messages=1, human_messages=1, assistant_messages=0,
            timestamps=["2026-03-13T10:00:00Z"],
        )
        profile = gs.compute_climate_profile(stats)
        # Should produce a cold, dry world
        self.assertLess(profile["temperature"], 0.20)


class TestJsonOutputFields(unittest.TestCase):
    """Verify JSON output contains all expected fields."""

    def _run_json(self, extra_args=""):
        import subprocess
        cmd = f"python3 scripts/generate_seed.py --all --json --db data/seeds_db.json {extra_args}"
        result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, f"Script failed: {result.stderr}")
        return json.loads(result.stdout)

    def test_default_json_has_all_fields(self):
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")
        data = self._run_json()
        for field in ["seed", "spawn_biome", "spawn_biome_display", "spawn_x", "spawn_z",
                       "compatibility", "chunkbase_url", "share_text", "profile", "stats", "mode"]:
            self.assertIn(field, data, f"Missing field: {field}")
        self.assertIn("chunkbase.com", data["chunkbase_url"])
        self.assertIn("#SeedCraft", data["share_text"])
        self.assertIn(str(data["seed"]), data["chunkbase_url"])

    def test_unique_json_has_all_fields(self):
        db_path = Path(__file__).resolve().parent.parent / "data" / "seeds_db.json"
        if not db_path.exists():
            self.skipTest("seeds_db.json not found")
        data = self._run_json("--unique")
        for field in ["seed", "spawn_biome", "compatibility", "chunkbase_url",
                       "share_text", "stats", "unique"]:
            self.assertIn(field, data, f"Missing field: {field}")
        self.assertNotIn("profile", data, "Unique mode should NOT include climate profile")
        self.assertTrue(data["unique"])
        self.assertIn("UNIQUE", data["share_text"])


class TestParserSubagentFormat(unittest.TestCase):
    """Verify subagent session files parse correctly."""

    def test_subagent_session(self):
        # Subagent sessions have the same format but are typically shorter
        lines = [
            json.dumps({"type": "user", "message": {"role": "user", "content": "search for auth"},
                         "timestamp": "2026-03-13T10:00:00Z", "uuid": "sa-1"}),
            json.dumps({"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-4-6",
                         "content": [{"type": "tool_use", "id": "t1", "name": "Grep", "input": {}}]},
                         "timestamp": "2026-03-13T10:00:05Z", "uuid": "sa-2"}),
        ]
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "agent-abc123.jsonl"
            fp.write_text("\n".join(lines) + "\n")
            stats = gs.parse_session_file(fp)
        self.assertEqual(stats["messages"], 2)
        self.assertEqual(stats["tool_calls"], 1)
        self.assertIn("Grep", stats["tools_used"])


class TestFindSessionFiles(unittest.TestCase):
    """Test that find_session_files discovers both main and subagent sessions."""

    def test_finds_main_and_subagent(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            # Main session
            (proj / "session1.jsonl").write_text("{}\n")
            # Subagent session
            sub_dir = proj / "session1" / "subagents"
            sub_dir.mkdir(parents=True)
            (sub_dir / "agent-abc.jsonl").write_text("{}\n")

            files = gs.find_session_files(proj)
            names = {f.name for f in files}
            self.assertIn("session1.jsonl", names)
            self.assertIn("agent-abc.jsonl", names)
            self.assertEqual(len(files), 2)

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as td:
            files = gs.find_session_files(Path(td))
            self.assertEqual(len(files), 0)


class TestCliModes(unittest.TestCase):
    """Test CLI invocation with various flags using subprocess."""

    def _run(self, args):
        import subprocess
        cmd = ["python3", "scripts/generate_seed.py"] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    def test_list_mode(self):
        result = self._run(["--list"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Project", result.stdout)

    def test_all_mode(self):
        result = self._run(["--all", "--db", "data/seeds_db.json"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("MINECRAFT SEED", result.stdout)

    def test_unique_mode(self):
        result = self._run(["--all", "--unique"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("Unique Seed", result.stdout)

    def test_stats_only_mode(self):
        result = self._run(["--all", "--stats-only"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("CLAUDE CODE STATS", result.stdout)

    def test_project_not_found(self):
        result = self._run(["--project", "nonexistent_zzzzz"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no project matching", result.stderr)

    def test_json_mode(self):
        result = self._run(["--all", "--json", "--db", "data/seeds_db.json"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertIn("seed", data)

    def test_unique_json_mode(self):
        result = self._run(["--all", "--unique", "--json"])
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertTrue(data["unique"])

    def test_no_flags_runs(self):
        # No flags = auto-detect CWD or fallback to all
        result = self._run(["--db", "data/seeds_db.json"])
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
