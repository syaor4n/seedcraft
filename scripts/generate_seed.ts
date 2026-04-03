#!/usr/bin/env node
/**
 * SeedCraft — Claude Code to Minecraft Seed Generator (TypeScript)
 *
 * Reads Claude Code session data from ~/.claude/, computes a climate profile
 * from usage statistics, and calls the SeedCraft API to select a curated
 * Minecraft seed whose spawn biome genuinely matches the profile.
 *
 * Usage:
 *   tsx scripts/generate_seed.ts --all --json
 *   tsx scripts/generate_seed.ts --project "my-project" --json
 *   tsx scripts/generate_seed.ts --list
 *   tsx scripts/generate_seed.ts --all --stats-only --json
 */

import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import * as crypto from "crypto";
import * as readline from "readline";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ToolCounter {
  [name: string]: number;
}

interface SessionStats {
  messages: number;
  human_messages: number;
  assistant_messages: number;
  tool_calls: number;
  tool_calls_by_name: ToolCounter;
  tools_used: Set<string>;
  total_chars: number;
  timestamps: (number | string)[];
  models_used: ToolCounter;
  error_count: number;
  agent_calls: number;
}

interface DerivedStats extends SessionStats {
  session_count: number;
  project_count: number;
  project_names: string[];
  total_duration_ms: number;
  session_durations: number[];
  avg_session_duration_ms: number;
  total_active_ms: number;
  hour_distribution: number[];
  night_ratio: number;
  read_calls: number;
  write_calls: number;
  execute_calls: number;
  orchestrate_calls: number;
  mcp_calls: number;
  write_ratio: number;
  tools_per_message: number;
  error_rate: number;
}

interface ClimateProfile {
  temperature: number;
  humidity: number;
  continentalness: number;
  erosion: number;
  weirdness: number;
  structure_density: number;
  biome_diversity: number;
}

interface ApiResult {
  seed: number;
  spawn_biome: string;
  spawn_biome_display?: string;
  spawn_x?: number;
  spawn_z?: number;
  compatibility?: string;
  chunkbase_url?: string;
  profile?: Partial<ClimateProfile>;
  biome_tier?: string;
}

interface SerializableStats {
  messages: number;
  human_messages: number;
  assistant_messages: number;
  tool_calls: number;
  unique_tools: number;
  top_tools: [string, number][];
  total_chars: number;
  project_count: number;
  project_names: string[];
  session_count: number;
  total_active_hours: number;
  avg_session_min: number;
  tools_per_message: number;
  write_ratio: number;
  error_rate: number;
}

interface ParsedArgs {
  all: boolean;
  project: string | null;
  unique: boolean;
  json: boolean;
  list: boolean;
  stats_only: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TOOLS_READ = new Set(["Read", "Grep", "Glob", "ToolSearch"]);
const TOOLS_WRITE = new Set(["Write", "Edit", "NotebookEdit"]);
const TOOLS_EXECUTE = new Set(["Bash"]);
const TOOLS_ORCHESTRATE = new Set([
  "Agent",
  "TaskCreate",
  "TaskUpdate",
  "TaskGet",
  "TaskList",
  "TaskStop",
  "TaskOutput",
]);

const SEEDCRAFT_API_URL = "https://seedcraft.dev/api/generate";
const SEEDCRAFT_TIMEOUT = 10_000; // 10 seconds in ms

// ---------------------------------------------------------------------------
// Normalisation helpers
// ---------------------------------------------------------------------------

function normalize(value: number, breakpoints: [number, number][]): number {
  if (value <= breakpoints[0][0]) return breakpoints[0][1];
  if (value >= breakpoints[breakpoints.length - 1][0])
    return breakpoints[breakpoints.length - 1][1];
  for (let i = 0; i < breakpoints.length - 1; i++) {
    const [x0, y0] = breakpoints[i];
    const [x1, y1] = breakpoints[i + 1];
    if (x0 <= value && value <= x1) {
      const t = x1 !== x0 ? (value - x0) / (x1 - x0) : 0;
      return y0 + t * (y1 - y0);
    }
  }
  return breakpoints[breakpoints.length - 1][1];
}

function fmt(n: number): string {
  return n.toLocaleString("en-US");
}

// ---------------------------------------------------------------------------
// Parsing — real Claude Code JSONL format
// ---------------------------------------------------------------------------

function createEmptyStats(): SessionStats {
  return {
    messages: 0,
    human_messages: 0,
    assistant_messages: 0,
    tool_calls: 0,
    tool_calls_by_name: {},
    tools_used: new Set(),
    total_chars: 0,
    timestamps: [],
    models_used: {},
    error_count: 0,
    agent_calls: 0,
  };
}

function parseSessionFile(filepath: string): SessionStats {
  const stats = createEmptyStats();

  let content: string;
  try {
    content = fs.readFileSync(filepath, "utf-8");
  } catch {
    process.stderr.write(`  Warning: could not read ${filepath}\n`);
    return stats;
  }

  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    let msg: any;
    try {
      msg = JSON.parse(trimmed);
    } catch {
      continue;
    }

    const msgType: string = msg.type ?? "";
    const ts = msg.timestamp;
    if (ts !== undefined && ts !== null) {
      stats.timestamps.push(ts);
    }

    if (msgType === "user") {
      stats.messages += 1;
      stats.human_messages += 1;
      const inner = msg.message ?? {};
      countContentChars(inner.content ?? "", stats);
      scanToolResults(inner.content ?? [], stats);
    } else if (msgType === "assistant") {
      stats.messages += 1;
      stats.assistant_messages += 1;
      const inner = msg.message ?? {};
      const model: string = inner.model ?? "unknown";
      if (model && model !== "<synthetic>") {
        stats.models_used[model] = (stats.models_used[model] ?? 0) + 1;
      }
      countContentChars(inner.content ?? "", stats);
      scanToolUses(inner.content ?? [], stats);
    }
  }

  return stats;
}

function countContentChars(content: any, stats: SessionStats): void {
  if (typeof content === "string") {
    stats.total_chars += content.length;
  } else if (Array.isArray(content)) {
    for (const block of content) {
      if (block && typeof block === "object") {
        const text = block.text;
        if (text) {
          stats.total_chars += String(text).length;
        }
      }
    }
  }
}

function scanToolUses(content: any, stats: SessionStats): void {
  if (!Array.isArray(content)) return;
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    if (block.type === "tool_use") {
      const name: string = block.name ?? "unknown";
      stats.tool_calls += 1;
      stats.tool_calls_by_name[name] =
        (stats.tool_calls_by_name[name] ?? 0) + 1;
      stats.tools_used.add(name);
      if (name === "Agent") {
        stats.agent_calls += 1;
      }
    }
  }
}

function scanToolResults(content: any, stats: SessionStats): void {
  if (!Array.isArray(content)) return;
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    if (block.type === "tool_result") {
      if (block.is_error) {
        stats.error_count += 1;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Stats aggregation
// ---------------------------------------------------------------------------

function mergeStats(allStats: SessionStats[]): SessionStats {
  const merged = createEmptyStats();
  for (const s of allStats) {
    merged.messages += s.messages;
    merged.human_messages += s.human_messages;
    merged.assistant_messages += s.assistant_messages;
    merged.tool_calls += s.tool_calls;
    for (const [name, count] of Object.entries(s.tool_calls_by_name)) {
      merged.tool_calls_by_name[name] =
        (merged.tool_calls_by_name[name] ?? 0) + count;
    }
    for (const tool of s.tools_used) {
      merged.tools_used.add(tool);
    }
    merged.total_chars += s.total_chars;
    merged.timestamps.push(...s.timestamps);
    for (const [model, count] of Object.entries(s.models_used)) {
      merged.models_used[model] = (merged.models_used[model] ?? 0) + count;
    }
    merged.error_count += s.error_count;
    merged.agent_calls += s.agent_calls;
  }
  return merged;
}

function tsToEpochMs(ts: number | string): number | null {
  if (typeof ts === "number") {
    return ts > 1e12 ? Math.floor(ts) : Math.floor(ts * 1000);
  }
  if (typeof ts === "string") {
    try {
      const cleaned = ts.replace("Z", "+00:00");
      const dt = new Date(cleaned);
      if (!isNaN(dt.getTime())) {
        return dt.getTime();
      }
    } catch {
      return null;
    }
  }
  return null;
}

function detectActiveSegments(
  epochList: number[],
  gapMs: number = 30 * 60 * 1000
): number[] {
  if (epochList.length < 2) return [];
  const segments: number[] = [];
  let segStart = epochList[0];
  let prev = epochList[0];
  for (let i = 1; i < epochList.length; i++) {
    const t = epochList[i];
    if (t - prev > gapMs) {
      const dur = prev - segStart;
      if (dur > 0) segments.push(dur);
      segStart = t;
    }
    prev = t;
  }
  const dur = prev - segStart;
  if (dur > 0) segments.push(dur);
  return segments;
}

function computeDerivedStats(
  stats: SessionStats,
  sessionCount: number,
  projectCount: number,
  projectNames: string[],
  perSessionDurations?: number[]
): DerivedStats {
  const derived = stats as any as DerivedStats;
  derived.session_count = sessionCount;
  derived.project_count = projectCount;
  derived.project_names = [...projectNames].sort();

  // Convert all timestamps to epoch-ms
  const epochList: number[] = [];
  for (const ts of stats.timestamps) {
    const ms = tsToEpochMs(ts);
    if (ms !== null) epochList.push(ms);
  }
  epochList.sort((a, b) => a - b);

  // Duration estimation from timestamps
  derived.total_duration_ms =
    epochList.length >= 2 ? epochList[epochList.length - 1] - epochList[0] : 0;

  // Per-session durations
  const sessionDurations =
    perSessionDurations && perSessionDurations.length > 0
      ? perSessionDurations
      : detectActiveSegments(epochList);
  derived.session_durations = sessionDurations;
  derived.avg_session_duration_ms =
    sessionDurations.length > 0
      ? sessionDurations.reduce((a, b) => a + b, 0) / sessionDurations.length
      : 0;
  derived.total_active_ms =
    sessionDurations.length > 0
      ? sessionDurations.reduce((a, b) => a + b, 0)
      : 0;

  // Hour-of-day distribution
  const hourDist = new Array(24).fill(0);
  for (const ms of epochList) {
    try {
      const dt = new Date(ms);
      hourDist[dt.getUTCHours()] += 1;
    } catch {
      // skip
    }
  }
  derived.hour_distribution = hourDist;
  const nightHours =
    hourDist.slice(0, 6).reduce((a, b) => a + b, 0) +
    hourDist.slice(22, 24).reduce((a, b) => a + b, 0);
  const dayHours = hourDist.slice(6, 22).reduce((a, b) => a + b, 0);
  derived.night_ratio = nightHours / Math.max(1, nightHours + dayHours);

  // Tool category counts
  const byName = stats.tool_calls_by_name;
  derived.read_calls = sumToolCounts(byName, TOOLS_READ);
  derived.write_calls = sumToolCounts(byName, TOOLS_WRITE);
  derived.execute_calls = sumToolCounts(byName, TOOLS_EXECUTE);
  derived.orchestrate_calls = sumToolCounts(byName, TOOLS_ORCHESTRATE);
  derived.mcp_calls = Object.entries(byName)
    .filter(([k]) => k.startsWith("mcp__"))
    .reduce((sum, [, v]) => sum + v, 0);

  // Ratios
  const totalRw = derived.read_calls + derived.write_calls;
  derived.write_ratio = derived.write_calls / Math.max(1, totalRw);
  derived.tools_per_message =
    stats.tool_calls / Math.max(1, stats.messages);
  derived.error_rate =
    stats.error_count / Math.max(1, stats.tool_calls);

  return derived;
}

function sumToolCounts(byName: ToolCounter, toolSet: Set<string>): number {
  let total = 0;
  for (const tool of toolSet) {
    total += byName[tool] ?? 0;
  }
  return total;
}

// ---------------------------------------------------------------------------
// Climate profile computation
// ---------------------------------------------------------------------------

function computeClimateProfile(stats: DerivedStats): ClimateProfile {
  const profile: ClimateProfile = {} as ClimateProfile;

  // Temperature: 5000 messages → 0.50 (center of biome space)
  profile.temperature = normalize(stats.messages, [
    [0, 0.15], [100, 0.20], [500, 0.28], [2000, 0.38],
    [5000, 0.50], [15000, 0.62], [40000, 0.75],
    [100000, 0.85], [500000, 0.92],
  ]);

  // Humidity: 2000 tool calls → 0.50
  profile.humidity = normalize(stats.tool_calls, [
    [0, 0.20], [50, 0.24], [200, 0.30], [800, 0.38],
    [2000, 0.50], [8000, 0.62], [20000, 0.72],
    [50000, 0.80], [200000, 0.85],
  ]);

  // Continentalness: 500 writes → 0.50
  profile.continentalness = normalize(stats.write_calls, [
    [0, 0.35], [10, 0.38], [50, 0.42], [200, 0.47],
    [500, 0.52], [2000, 0.62], [5000, 0.72],
    [10000, 0.80], [30000, 0.88],
  ]);

  // Erosion (inverted): 20 hours → 0.50
  const totalHours = stats.total_active_ms / 3_600_000;
  profile.erosion = normalize(totalHours, [
    [0, 0.85], [1, 0.78], [3, 0.70], [8, 0.60],
    [20, 0.50], [50, 0.38], [100, 0.28],
    [250, 0.18], [500, 0.15],
  ]);

  // Weirdness: 15 unique tools → 0.50
  const uniqueTools = stats.tools_used.size;
  profile.weirdness = normalize(uniqueTools, [
    [0, 0.15], [3, 0.22], [7, 0.32], [12, 0.42],
    [20, 0.55], [35, 0.65], [50, 0.75],
    [75, 0.82], [120, 0.88],
  ]);

  // Structure density: agent + orchestration calls
  const orchestrate = stats.agent_calls + stats.orchestrate_calls;
  profile.structure_density = normalize(orchestrate, [
    [0, 0.00], [5, 0.10], [15, 0.22], [40, 0.38],
    [100, 0.55], [250, 0.72], [500, 0.88],
    [1000, 0.95], [3000, 1.00],
  ]);

  // Biome diversity: project count
  profile.biome_diversity = normalize(stats.project_count, [
    [1, 0.08], [2, 0.18], [3, 0.28], [5, 0.42],
    [8, 0.58], [12, 0.72], [20, 0.88],
    [40, 0.96], [80, 1.00],
  ]);

  return profile;
}

// ---------------------------------------------------------------------------
// Unique seed generation (hash-based)
// ---------------------------------------------------------------------------

function generateUniqueSeed(stats: DerivedStats): number {
  const canonical = JSON.stringify(
    {
      messages: stats.messages,
      human_messages: stats.human_messages,
      assistant_messages: stats.assistant_messages,
      tool_calls: stats.tool_calls,
      unique_tools: [...stats.tools_used].sort(),
      total_chars: stats.total_chars,
      project_names: stats.project_names,
      session_count: stats.session_count,
      total_active_ms: stats.total_active_ms,
      error_count: stats.error_count,
      agent_calls: stats.agent_calls,
      read_calls: stats.read_calls,
      write_calls: stats.write_calls,
      execute_calls: stats.execute_calls,
      mcp_calls: stats.mcp_calls,
      models: Object.keys(stats.models_used).sort(),
    },
    null,
    undefined
  );

  // Sort keys for determinism (JSON.stringify with replacer)
  const sortedCanonical = JSON.stringify(
    JSON.parse(canonical),
    Object.keys(JSON.parse(canonical)).sort()
  );

  const digest = crypto.createHash("sha256").update(sortedCanonical, "utf-8").digest();
  // First 4 bytes -> signed 32-bit int (Bedrock-compatible), big-endian
  const seed = digest.readInt32BE(0);
  return seed;
}

// ---------------------------------------------------------------------------
// Biome labels
// ---------------------------------------------------------------------------

const BIOME_LABELS: Record<string, string> = {
  desert: "DESERT",
  jungle: "JUNGLE",
  bamboo_jungle: "BAMBOO JUNGLE",
  sparse_jungle: "SPARSE JUNGLE",
  plains: "PLAINS",
  sunflower_plains: "SUNFLOWER PLAINS",
  forest: "FOREST",
  birch_forest: "BIRCH FOREST",
  old_growth_birch_forest: "OLD GROWTH BIRCH FOREST",
  dark_forest: "DARK FOREST",
  flower_forest: "FLOWER FOREST",
  taiga: "TAIGA",
  old_growth_spruce_taiga: "OLD GROWTH SPRUCE TAIGA",
  old_growth_pine_taiga: "OLD GROWTH PINE TAIGA",
  snowy_plains: "SNOWY PLAINS",
  snowy_taiga: "SNOWY TAIGA",
  frozen_peaks: "FROZEN PEAKS",
  stony_peaks: "STONY PEAKS",
  jagged_peaks: "JAGGED PEAKS",
  snowy_slopes: "SNOWY SLOPES",
  savanna: "SAVANNA",
  savanna_plateau: "SAVANNA PLATEAU",
  windswept_savanna: "WINDSWEPT SAVANNA",
  badlands: "BADLANDS",
  wooded_badlands: "WOODED BADLANDS",
  eroded_badlands: "ERODED BADLANDS",
  swamp: "SWAMP",
  mangrove_swamp: "MANGROVE SWAMP",
  mushroom_fields: "MUSHROOM FIELDS",
  ocean: "OCEAN",
  deep_ocean: "DEEP OCEAN",
  warm_ocean: "WARM OCEAN",
  lukewarm_ocean: "LUKEWARM OCEAN",
  cold_ocean: "COLD OCEAN",
  frozen_ocean: "FROZEN OCEAN",
  deep_lukewarm_ocean: "DEEP LUKEWARM OCEAN",
  deep_cold_ocean: "DEEP COLD OCEAN",
  deep_frozen_ocean: "DEEP FROZEN OCEAN",
  beach: "BEACH",
  snowy_beach: "SNOWY BEACH",
  stony_shore: "STONY SHORE",
  cherry_grove: "CHERRY GROVE",
  meadow: "MEADOW",
  windswept_hills: "WINDSWEPT HILLS",
  windswept_forest: "WINDSWEPT FOREST",
  grove: "GROVE",
  dripstone_caves: "DRIPSTONE CAVES",
  lush_caves: "LUSH CAVES",
  ice_spikes: "ICE SPIKES",
  pale_garden: "PALE GARDEN",
};

// ---------------------------------------------------------------------------
// Share URL generation
// ---------------------------------------------------------------------------

function makeShareCard(
  seed: number,
  biomeDisplay: string,
  stats: DerivedStats,
  profile: ClimateProfile | null,
  unique: boolean = false
): { share_text: string; gallery_url: string } {
  const totalH = stats.total_active_ms / 3_600_000;
  const msgs = fmt(stats.messages);
  const tools = fmt(stats.tool_calls);

  let shareText: string;
  if (unique) {
    shareText = `#SeedCraft | UNIQUE | ${msgs} msgs, ${tools} tools, ${totalH.toFixed(0)}h coding`;
  } else {
    const temp = Math.floor((profile!.temperature) * 100);
    const humid = Math.floor((profile!.humidity) * 100);
    const elev = Math.floor((1 - profile!.erosion) * 100);
    shareText = `#SeedCraft | ${biomeDisplay} | ${temp}% hot, ${humid}% humid, ${elev}% elevation | ${totalH.toFixed(0)}h coding`;
  }

  // Pre-filled gallery submission URL
  const galleryParams: Record<string, string> = {
    seed: String(seed),
    comment: `${totalH.toFixed(0)}h of coding, ${stats.messages.toLocaleString("en-US")} messages`,
    stat_messages: String(stats.messages),
    stat_tool_calls: String(stats.tool_calls),
    stat_active_hours: (stats.total_active_ms / 3_600_000).toFixed(1),
  };

  if (!unique && profile) {
    galleryParams.biome = biomeDisplay.toLowerCase().replace(/ /g, "_");
    for (const key of [
      "temperature",
      "humidity",
      "continentalness",
      "erosion",
      "weirdness",
      "structure_density",
      "biome_diversity",
    ] as (keyof ClimateProfile)[]) {
      galleryParams[key] = profile[key].toFixed(4);
    }
  }

  const paramString = new URLSearchParams(galleryParams).toString();
  const galleryUrl = `https://seedcraft.dev/gallery?share&${paramString}`;

  return { share_text: shareText, gallery_url: galleryUrl };
}

// ---------------------------------------------------------------------------
// Serializable stats helper
// ---------------------------------------------------------------------------

function serializableStats(stats: DerivedStats): SerializableStats {
  // Top 5 tools
  const topTools: [string, number][] = Object.entries(stats.tool_calls_by_name)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);

  return {
    messages: stats.messages,
    human_messages: stats.human_messages,
    assistant_messages: stats.assistant_messages,
    tool_calls: stats.tool_calls,
    unique_tools: stats.tools_used.size,
    top_tools: topTools,
    total_chars: stats.total_chars,
    project_count: stats.project_count,
    project_names: stats.project_names,
    session_count: stats.session_count,
    total_active_hours: Math.round((stats.total_active_ms / 3_600_000) * 100) / 100,
    avg_session_min: Math.round((stats.avg_session_duration_ms / 60_000) * 10) / 10,
    tools_per_message: Math.round(stats.tools_per_message * 1000) / 1000,
    write_ratio: Math.round(stats.write_ratio * 1000) / 1000,
    error_rate: Math.round(stats.error_rate * 10000) / 10000,
  };
}

// ---------------------------------------------------------------------------
// Bedrock check
// ---------------------------------------------------------------------------

function isBedrockSafe(seed: number): boolean {
  return seed >= -2147483648 && seed <= 2147483647;
}

// ---------------------------------------------------------------------------
// Project discovery
// ---------------------------------------------------------------------------

function findClaudeDir(): string {
  const claudeDir = path.join(os.homedir(), ".claude");
  if (!fs.existsSync(claudeDir)) {
    process.stderr.write("Error: ~/.claude directory not found.\n");
    process.stderr.write(
      "Make sure Claude Code is installed and has been used.\n"
    );
    process.exit(1);
  }
  return claudeDir;
}

function findProjects(claudeDir: string): string[] {
  const projectsDir = path.join(claudeDir, "projects");
  if (!fs.existsSync(projectsDir)) return [];
  try {
    const entries = fs.readdirSync(projectsDir, { withFileTypes: true });
    return entries
      .filter((e) => e.isDirectory())
      .map((e) => path.join(projectsDir, e.name))
      .sort();
  } catch {
    return [];
  }
}

function findSessionFiles(directory: string): string[] {
  const files = new Set<string>();

  // Main sessions at project root
  try {
    for (const entry of fs.readdirSync(directory)) {
      if (entry.endsWith(".jsonl")) {
        const fp = path.join(directory, entry);
        if (fs.statSync(fp).isFile()) {
          files.add(fp);
        }
      }
    }
  } catch {
    // directory might not be readable
  }

  // Subagent sessions: look for */subagents/*.jsonl
  try {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        const subagentsDir = path.join(directory, entry.name, "subagents");
        try {
          if (fs.existsSync(subagentsDir) && fs.statSync(subagentsDir).isDirectory()) {
            for (const subEntry of fs.readdirSync(subagentsDir)) {
              if (subEntry.endsWith(".jsonl")) {
                const fp = path.join(subagentsDir, subEntry);
                if (fs.statSync(fp).isFile()) {
                  files.add(fp);
                }
              }
            }
          }
        } catch {
          // subagents dir might not exist or be readable
        }
      }
    }
  } catch {
    // directory might not be readable
  }

  return [...files].sort();
}

function prettyProjectName(rawName: string): string {
  const stripped = rawName.replace(/^-+|-+$/g, "");
  if (!stripped) return "(root)";

  const parts = stripped.split("-");
  const containers = new Set([
    "Sites",
    "Projects",
    "Documents",
    "repos",
    "src",
    "code",
    "dev",
    "home",
    "Home",
    "work",
    "workspace",
    "Desktop",
    "AndroidStudioProjects",
    "IdeaProjects",
  ]);

  let lastContainer = -1;
  for (let i = 0; i < parts.length; i++) {
    if (containers.has(parts[i])) {
      lastContainer = i;
    }
  }

  if (lastContainer >= 0 && lastContainer < parts.length - 1) {
    return parts.slice(lastContainer + 1).join("-");
  }

  // Fallback: skip Users-<username> prefix
  if (parts.length > 2 && parts[0] === "Users") {
    return parts.slice(2).join("-");
  }
  return stripped;
}

function listProjects(claudeDir: string): void {
  const projects = findProjects(claudeDir);
  if (projects.length === 0) {
    console.log("No projects found in ~/.claude/projects/");
    return;
  }

  console.log();
  console.log(`  ${"Project".padEnd(35)} ${"Sessions".padStart(8)}`);
  console.log(`  ${"─".repeat(35)} ${"─".repeat(8)}`);
  let totalSessions = 0;
  for (const proj of projects) {
    const sessions = findSessionFiles(proj);
    const name = prettyProjectName(path.basename(proj));
    totalSessions += sessions.length;
    console.log(`  ${name.padEnd(35)} ${String(sessions.length).padStart(8)}`);
  }
  console.log(`  ${"─".repeat(35)} ${"─".repeat(8)}`);
  console.log(`  ${"Total".padEnd(35)} ${String(totalSessions).padStart(8)}`);
  console.log();
}

function detectCwdProject(projects: string[]): string | null {
  let cwd: string;
  try {
    cwd = path.resolve(process.cwd());
  } catch {
    return null;
  }

  // Encode CWD the same way Claude Code does: replace / with -
  const cwdEncoded = cwd.replace(/\//g, "-");
  for (const p of projects) {
    if (path.basename(p) === cwdEncoded) return p;
  }

  // Also try parent directories
  const parts = cwd.split("/");
  for (let i = parts.length - 1; i > 1; i--) {
    const parent = parts.slice(0, i).join("/");
    const parentEncoded = parent.replace(/\//g, "-");
    for (const p of projects) {
      if (path.basename(p) === parentEncoded) return p;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// API integration
// ---------------------------------------------------------------------------

function buildApiStats(stats: DerivedStats): Record<string, number> {
  return {
    messages: stats.messages,
    tool_calls: stats.tool_calls,
    write_calls: stats.write_calls,
    total_active_hours: stats.total_active_ms / 3_600_000,
    unique_tools: stats.tools_used.size,
    agent_calls: stats.agent_calls,
    orchestrate_calls: stats.orchestrate_calls,
    project_count: stats.project_count,
  };
}

async function tryApiGenerate(
  stats: DerivedStats,
  mode: "curated" | "unique" = "curated"
): Promise<ApiResult | null> {
  try {
    const payload = JSON.stringify({
      mode,
      stats: buildApiStats(stats),
    });

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), SEEDCRAFT_TIMEOUT);

    const response = await fetch(SEEDCRAFT_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.ok) {
      return (await response.json()) as ApiResult;
    }
  } catch {
    // Network error, timeout, API down — fall back silently
  }
  return null;
}

// ---------------------------------------------------------------------------
// CLI argument parsing
// ---------------------------------------------------------------------------

function parseArgs(): ParsedArgs {
  const args = process.argv.slice(2);
  const parsed: ParsedArgs = {
    all: false,
    project: null,
    unique: false,
    json: false,
    list: false,
    stats_only: false,
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--all":
        parsed.all = true;
        break;
      case "--project":
        i++;
        parsed.project = args[i] ?? null;
        break;
      case "--unique":
        parsed.unique = true;
        break;
      case "--json":
        parsed.json = true;
        break;
      case "--list":
        parsed.list = true;
        break;
      case "--stats-only":
        parsed.stats_only = true;
        break;
      default:
        process.stderr.write(`Unknown argument: ${args[i]}\n`);
        process.exit(1);
    }
  }

  return parsed;
}

// ---------------------------------------------------------------------------
// ASCII box rendering (for non-JSON output)
// ---------------------------------------------------------------------------

const BOX_W = 60;

function bar(value: number, width: number = 12): string {
  const filled = Math.round(value * width);
  return "\u2588".repeat(filled) + "\u2591".repeat(width - filled);
}

function boxLine(text: string = "", w: number = BOX_W): string {
  const pad = Math.max(0, w - 2 - text.length);
  return `\u2551 ${text}${" ".repeat(pad)} \u2551`;
}

function boxTop(w: number = BOX_W): string {
  return "\u2554" + "\u2550".repeat(w) + "\u2557";
}

function boxMid(w: number = BOX_W): string {
  return "\u2560" + "\u2550".repeat(w) + "\u2563";
}

function boxBot(w: number = BOX_W): string {
  return "\u255a" + "\u2550".repeat(w) + "\u255d";
}

function boxSep(char: string = "\u2500", w: number = BOX_W): string {
  return boxLine(char.repeat(w - 4), w);
}

function climateLabel(param: string, value: number): string {
  const labels: Record<string, [number, string][]> = {
    temperature: [
      [0.15, "Frozen"], [0.30, "Cold"], [0.45, "Cool"],
      [0.60, "Mild"], [0.75, "Warm"], [0.90, "Hot"], [1.01, "Scorching"],
    ],
    humidity: [
      [0.15, "Arid"], [0.30, "Dry"], [0.45, "Moderate"],
      [0.60, "Humid"], [0.75, "Wet"], [0.90, "Tropical"], [1.01, "Drenched"],
    ],
    continentalness: [
      [0.20, "Deep Ocean"], [0.35, "Ocean"], [0.50, "Coast"],
      [0.65, "Inland"], [0.80, "Continental"], [1.01, "Far Inland"],
    ],
    erosion: [
      [0.20, "Jagged Peaks"], [0.35, "Mountains"], [0.50, "Hills"],
      [0.65, "Rolling"], [0.80, "Gentle"], [1.01, "Flat"],
    ],
    weirdness: [
      [0.20, "Normal"], [0.40, "Unusual"], [0.60, "Strange"],
      [0.80, "Bizarre"], [1.01, "Alien"],
    ],
    structure_density: [
      [0.20, "Wilderness"], [0.40, "Sparse"], [0.60, "Settled"],
      [0.80, "Populated"], [1.01, "Metropolis"],
    ],
    biome_diversity: [
      [0.20, "Monotone"], [0.40, "Limited"], [0.60, "Varied"],
      [0.80, "Diverse"], [1.01, "Kaleidoscope"],
    ],
  };

  for (const [threshold, label] of labels[param] ?? []) {
    if (value < threshold) return label;
  }
  return "Unknown";
}

function renderClimateBars(profile: ClimateProfile, lines: string[]): void {
  const params: [keyof ClimateProfile, string][] = [
    ["temperature", "Temperature  "],
    ["humidity", "Humidity     "],
    ["erosion", "Elevation    "],
    ["continentalness", "Continental  "],
    ["weirdness", "Weirdness    "],
    ["structure_density", "Structures   "],
    ["biome_diversity", "Diversity    "],
  ];

  for (const [key, label] of params) {
    const val = profile[key];
    const displayVal = key === "erosion" ? 1.0 - val : val;
    const pct = Math.floor(displayVal * 100);
    const cl = climateLabel(key, val);
    const b = bar(displayVal);
    lines.push(boxLine(`  ${label} ${b}  ${String(pct).padStart(3)}%  ${cl}`));
  }
}

function renderStatsSection(
  stats: DerivedStats,
  modeLabel: string,
  lines: string[]
): void {
  lines.push(boxLine(`Stats (${modeLabel})`));
  lines.push(boxLine());
  lines.push(
    boxLine(
      `  Messages:     ${fmt(stats.messages).padStart(10)}  (${fmt(stats.human_messages)} you / ${fmt(stats.assistant_messages)} AI)`
    )
  );
  lines.push(
    boxLine(
      `  Tool calls:   ${fmt(stats.tool_calls).padStart(10)}  (${stats.tools_used.size} unique tools)`
    )
  );
  lines.push(boxLine(`  Projects:     ${String(stats.project_count).padStart(10)}`));
  const totalH = stats.total_active_ms / 3_600_000;
  lines.push(
    boxLine(
      `  Active time:  ${totalH.toFixed(1).padStart(9)}h  (${stats.session_count} sessions)`
    )
  );
  lines.push(boxLine(`  Characters:   ${fmt(stats.total_chars).padStart(10)}`));
  if (Object.keys(stats.models_used).length > 0) {
    const topModel = Object.entries(stats.models_used).sort(
      (a, b) => b[1] - a[1]
    )[0][0];
    lines.push(boxLine(`  Top model:    ${topModel.padStart(10)}`));
  }
  const top5 = Object.entries(stats.tool_calls_by_name)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
  if (top5.length > 0) {
    lines.push(boxLine());
    lines.push(boxLine("  Top tools:"));
    for (const [name, count] of top5) {
      lines.push(boxLine(`    ${name.padEnd(20)} ${fmt(count).padStart(8)}`));
    }
  }
}

function wrapLines(text: string, lines: string[], width: number): void {
  const words = text.split(/\s+/);
  let current = "  ";
  for (const word of words) {
    if (current.length + word.length + 1 > width) {
      if (current.trim()) lines.push(boxLine(current));
      current = "  " + word;
    } else {
      current += (current.length > 2 ? " " : "") + word;
    }
  }
  if (current.trim()) lines.push(boxLine(current));
}

// ---------------------------------------------------------------------------
// Biome narratives (for non-JSON output)
// ---------------------------------------------------------------------------

const BIOME_NARRATIVES: Record<string, string> = {
  desert:
    "Your {messages} messages scorched the atmosphere. The desert reflects a direct, focused coding style — maximum intent, minimum overhead.",
  jungle:
    "Your {messages} messages raised the temperature while {tool_calls} tool calls nurtured dense vegetation. A lush jungle forged by relentless productivity.",
  bamboo_jungle:
    "Extreme heat from {messages} messages and extreme humidity from {tool_calls} tool calls. Your world is a wall of bamboo — impenetrable productivity.",
  plains:
    "Balanced and steady. Moderate warmth, moderate humidity across {projects} projects. A world of open possibility.",
  sunflower_plains:
    "A gentle coder's world. Your {messages} messages bring mild warmth, and your balanced tooling lets sunflowers bloom.",
  forest:
    "A natural equilibrium of conversation and tooling across {projects} projects. The forest mirrors a healthy workflow.",
  birch_forest:
    "Light and organized. Your sessions average {avg_min} minutes — short, productive, and bright like birch bark.",
  dark_forest:
    "Dense tool usage casts deep shadows. {tool_calls} tool calls created a canopy so thick, hostile mobs lurk below.",
  flower_forest:
    "Your {unique_tools} unique tools paint the forest floor with color. A diverse, beautiful workflow.",
  taiga:
    "Cool and methodical. Your {messages} messages keep things grounded, like the spruce forests of the taiga.",
  old_growth_spruce_taiga:
    "Ancient trees for a veteran coder. {hours} hours of sessions grew old-growth spruce that tower above all.",
  snowy_plains:
    "A quiet, pristine world. Your {messages} messages leave careful footprints in fresh snow. The snowy plains reward a measured, deliberate approach.",
  snowy_taiga:
    "A cool, quiet world. Your moderate pace across {projects} projects keeps things frosty but alive with spruce.",
  frozen_peaks:
    "Minimal messages but {hours} hours of marathon sessions raised frozen peaks. Quiet intensity at its finest.",
  jagged_peaks:
    "{hours} hours of relentless sessions pushed the terrain into jagged spires. These peaks were forged by persistence.",
  stony_peaks:
    "Hot climate meets extreme elevation. Your {messages} messages heat the stone while {hours} hours raised the peaks.",
  savanna:
    "Warm but not tropical. Active messaging with selective tool usage creates wide-open savanna — efficient and expansive.",
  badlands:
    "Your {messages} messages pushed heat to the extreme. {hours} hours of intense sessions sculpted red mesas from the scorched earth.",
  swamp:
    "High humidity from {tool_calls} tool calls meets moderate warmth. The swamp mirrors your tool-heavy, exploratory workflow.",
  mangrove_swamp:
    "Tropical heat and {tool_calls} tool calls saturated the air. A tangled mangrove where your code roots run deep.",
  mushroom_fields:
    "With {unique_tools} unique tools — the most exotic arsenal — your world manifests as the rarest biome. Pure weirdness.",
  ocean:
    "A reader more than a writer. Your {reads} reads vs {writes} writes created vast oceans of knowledge. Dive deep.",
  deep_ocean:
    "Read-heavy with {reads} reads, your code exploration carved deep ocean trenches. Knowledge runs unfathomably deep.",
  warm_ocean:
    "Warm from {messages} messages and oceanic from your read-heavy style ({reads} reads). Coral reefs thrive in your workflow.",
  beach:
    "Right at the boundary between reading and writing. Your balanced ratio places you on the shore.",
  cherry_grove:
    "Moderate and pleasant. Not too hot, not too cold. Your {projects} projects bloom like cherry trees in spring.",
  meadow:
    "A gentle, elevated meadow. Your {hours} hours of coding lifted the terrain, and balanced stats keep it serene.",
  windswept_hills:
    "Your {hours} hours of sessions whipped up windswept hills. Not the tallest, but the breeze of productivity is constant.",
  grove:
    "Cool temperatures meet moderate elevation. Your measured approach across {projects} projects grew a peaceful grove.",
  dripstone_caves:
    "Your {tool_calls} tool calls drilled deep into the earth. Each call a stalactite dripping from the ceiling. A subterranean coder's paradise.",
  lush_caves:
    "Your {tool_calls} tool calls saturated the underground with humidity. Glow berries bloom in caverns carved by relentless exploration.",
  old_growth_birch_forest:
    "Tall birch trees mark a seasoned coder. Your {messages} messages across {projects} projects grew an ancient, towering birch forest.",
  old_growth_pine_taiga:
    "Massive pines for a veteran. Your {hours} hours of sessions and {messages} messages grew a primeval pine forest that dwarfs all others.",
  sparse_jungle:
    "Warm from {messages} messages but not quite tropical. Your {tool_calls} tool calls thin the jungle canopy into a sparse, navigable forest.",
  stony_shore:
    "Where ocean meets continent. Your balanced read/write ratio ({reads} reads, {writes} writes) places you on a rugged, rocky shoreline.",
  snowy_beach:
    "Cold and coastal. Few messages keep the temperature low, while your read-heavy style ({reads} reads) pulls the world toward the ocean.",
  savanna_plateau:
    "Warm and elevated. Your {messages} messages bring heat while {hours} hours of sessions raised a flat-topped plateau above the savanna.",
  windswept_savanna:
    "Hot and wild. Your {messages} messages scorch the landscape while {tool_calls} tool calls whip the savanna into windswept chaos.",
  wooded_badlands:
    "Your {messages} messages and {writes} writes forged towering red mesas. Oak trees took root at the peaks. A rare biome for a rare coding intensity.",
  eroded_badlands:
    "Your {messages} messages scorched the earth. Time eroded the mesas into dramatic spires. {hours} hours of relentless coding carved this landscape.",
  snowy_slopes:
    "Cold and elevated. Your modest message count keeps things frosty, while {hours} hours of sessions pushed the terrain upward into snow-covered slopes.",
  windswept_forest:
    "Moderate temperatures meet high elevation. Your {hours} hours of marathon sessions raised windswept forests where the trees lean with the gale.",
  ice_spikes:
    "Frozen and bizarre. Low message count keeps the world frigid, while your {unique_tools} unique tools sculpted towering ice spikes from the permafrost.",
  pale_garden:
    "A ghostly, muted world. Your quiet, measured coding style across {projects} projects conjured the rarest biome — a pale garden shrouded in silence.",
  lukewarm_ocean:
    "Mildly warm from {messages} messages, your read-heavy workflow ({reads} reads) created a lukewarm ocean. Tropical fish swim just beneath the surface.",
  cold_ocean:
    "Cool and deep. Your moderate messaging and read-heavy style ({reads} reads vs {writes} writes) chilled the waters into a cold ocean.",
  frozen_ocean:
    "A frozen expanse. Few messages keep the world icy, and your read-heavy approach spreads vast, frozen oceans across the map.",
  deep_lukewarm_ocean:
    "Deep and mildly warm. Your {reads} reads carved ocean trenches while {messages} messages kept the water just above freezing.",
  deep_cold_ocean:
    "Frigid depths. Your read-heavy exploration ({reads} reads) plunged into cold, dark waters far from shore.",
  deep_frozen_ocean:
    "The deepest freeze. Minimal messages and maximum reading created an ocean so cold and deep, icebergs scrape the ocean floor.",
};

const BIOME_FALLBACK =
  "Your unique combination of {messages} messages, {tool_calls} tool calls across {projects} projects created a one-of-a-kind world.";

function getNarrative(biome: string, stats: DerivedStats): string {
  const template = BIOME_NARRATIVES[biome] ?? BIOME_FALLBACK;
  const totalHours = stats.total_active_ms / 3_600_000;
  const avgMin = stats.avg_session_duration_ms / 60_000;
  return template
    .replace(/\{messages\}/g, fmt(stats.messages))
    .replace(/\{tool_calls\}/g, fmt(stats.tool_calls))
    .replace(/\{tpm\}/g, String(stats.tools_per_message))
    .replace(/\{projects\}/g, String(stats.project_count))
    .replace(/\{hours\}/g, totalHours.toFixed(0))
    .replace(/\{avg_min\}/g, avgMin.toFixed(0))
    .replace(/\{unique_tools\}/g, String(stats.tools_used.size))
    .replace(/\{reads\}/g, fmt(stats.read_calls))
    .replace(/\{writes\}/g, fmt(stats.write_calls));
}

// ---------------------------------------------------------------------------
// Render functions (non-JSON output)
// ---------------------------------------------------------------------------

function renderStatsOnly(
  profile: ClimateProfile,
  stats: DerivedStats,
  modeLabel: string
): void {
  const lines: string[] = [];
  lines.push(boxTop());
  lines.push(boxLine("CLAUDE CODE STATS"));
  lines.push(boxMid());
  lines.push(boxLine());
  lines.push(boxLine("Climate Profile"));
  lines.push(boxLine());
  renderClimateBars(profile, lines);
  lines.push(boxLine());
  lines.push(boxSep());
  renderStatsSection(stats, modeLabel, lines);
  lines.push(boxLine());
  lines.push(boxBot());
  console.log(lines.join("\n"));
}

function renderOutput(
  seedEntry: { seed: number; spawn_biome: string; spawn_x?: number; spawn_z?: number },
  profile: ClimateProfile,
  stats: DerivedStats,
  modeLabel: string
): void {
  const seed = seedEntry.seed;
  const biome = seedEntry.spawn_biome;
  const biomeDisplay =
    BIOME_LABELS[biome] ?? biome.toUpperCase().replace(/_/g, " ");
  const spawnX = seedEntry.spawn_x ?? 0;
  const spawnZ = seedEntry.spawn_z ?? 0;

  const lines: string[] = [];
  lines.push(boxTop());
  lines.push(boxLine("CLAUDE CODE -> MINECRAFT SEED"));
  lines.push(boxMid());
  lines.push(boxLine());
  const compat = isBedrockSafe(seed) ? "Java & Bedrock" : "Java only";
  lines.push(boxLine(`Seed: ${seed}`));
  lines.push(boxLine(`Spawn: (${spawnX}, ${spawnZ})  [${compat}]`));
  lines.push(boxLine());
  lines.push(boxSep());
  lines.push(boxLine("Climate Profile"));
  lines.push(boxLine());
  renderClimateBars(profile, lines);
  lines.push(boxLine());
  lines.push(boxSep());
  lines.push(boxLine(`Predicted Biome: ${biomeDisplay}`));
  lines.push(boxLine());

  const narrative = getNarrative(biome, stats);
  wrapLines(narrative, lines, 54);

  lines.push(boxLine());
  lines.push(boxSep());
  renderStatsSection(stats, modeLabel, lines);
  lines.push(boxLine());
  lines.push(boxSep());
  lines.push(boxLine("How to use:"));
  lines.push(boxLine("  1. Copy the seed number"));
  lines.push(boxLine("  2. Minecraft > Create New World > Seed"));
  lines.push(boxLine("  3. Paste and play  (Java & Bedrock 1.18+)"));
  lines.push(boxLine());
  lines.push(boxLine(`Preview: chunkbase.com/apps/seed-map#${seed}`));
  lines.push(boxLine());
  lines.push(boxLine("Deterministic: same stats = same world."));
  lines.push(boxBot());

  console.log(lines.join("\n"));

  const totalH = stats.total_active_ms / 3_600_000;
  const elev = Math.floor((1 - profile.erosion) * 100);
  const temp = Math.floor(profile.temperature * 100);
  const humid = Math.floor(profile.humidity * 100);
  console.log();
  console.log(
    `  #SeedCraft | ${biomeDisplay} | ${temp}% hot, ${humid}% humid, ${elev}% elevation | ${totalH.toFixed(0)}h coding`
  );
  console.log();
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const args = parseArgs();
  const claudeDir = findClaudeDir();

  // --list mode
  if (args.list) {
    listProjects(claudeDir);
    return;
  }

  const projects = findProjects(claudeDir);
  if (projects.length === 0) {
    process.stderr.write("Error: no projects found in ~/.claude/projects/\n");
    process.exit(1);
  }

  // Determine target: --project > --all > auto-detect CWD > fallback to all
  let targetProjects: string[];
  let modeLabel: string;

  if (args.project) {
    const search = args.project
      .toLowerCase()
      .replace(/[\s\-_]/g, "");
    const matched: string[] = [];
    for (const p of projects) {
      const rawName = path.basename(p);
      const rawNorm = rawName.toLowerCase().replace(/[\-_]/g, "");
      const prettyNorm = prettyProjectName(rawName)
        .toLowerCase()
        .replace(/[\-_]/g, "");
      if (!rawNorm) continue;
      if (
        rawNorm.includes(search) ||
        (rawNorm.length > 2 && search.includes(rawNorm)) ||
        prettyNorm.includes(search)
      ) {
        matched.push(p);
      }
    }

    if (matched.length === 0) {
      process.stderr.write(`Error: no project matching '${args.project}'.\n`);
      process.stderr.write("Available (use --list for details):\n");
      for (const p of projects) {
        process.stderr.write(
          `  - ${prettyProjectName(path.basename(p))}\n`
        );
      }
      process.exit(1);
    }

    targetProjects = matched;
    modeLabel =
      matched.length === 1
        ? `project: ${prettyProjectName(path.basename(matched[0]))}`
        : `${matched.length} projects matching '${args.project}'`;
  } else if (args.all) {
    targetProjects = projects;
    modeLabel = "all projects";
  } else {
    // Auto-detect: match current working directory to a project
    const cwdProject = detectCwdProject(projects);
    if (cwdProject) {
      targetProjects = [cwdProject];
      modeLabel = `project: ${prettyProjectName(path.basename(cwdProject))}`;
    } else {
      targetProjects = projects;
      modeLabel = "all projects";
    }
  }

  // Collect stats
  const allStats: SessionStats[] = [];
  const projectNames: string[] = [];
  let sessionCount = 0;
  const perSessionDurations: number[] = [];

  for (const projDir of targetProjects) {
    const sessionFiles = findSessionFiles(projDir);
    if (sessionFiles.length === 0) continue;
    projectNames.push(prettyProjectName(path.basename(projDir)));
    for (const sf of sessionFiles) {
      const fileStats = parseSessionFile(sf);
      if (fileStats.messages > 0) {
        allStats.push(fileStats);
        sessionCount += 1;
        // Compute active time per-file with gap detection
        const epochs = fileStats.timestamps
          .map((t) => tsToEpochMs(t))
          .filter((ms): ms is number => ms !== null)
          .sort((a, b) => a - b);
        perSessionDurations.push(...detectActiveSegments(epochs));
      }
    }
  }

  if (allStats.length === 0) {
    if (args.json) {
      console.log(JSON.stringify({ error: "No session data found." }));
    } else {
      process.stderr.write("Error: no session data found.\n");
    }
    process.exit(1);
  }

  // Merge & derive
  const merged = mergeStats(allStats);
  const derived = computeDerivedStats(
    merged,
    sessionCount,
    projectNames.length,
    projectNames,
    perSessionDurations
  );

  // Climate profile
  const profile = computeClimateProfile(derived);

  // --stats-only mode
  if (args.stats_only) {
    if (args.json) {
      console.log(
        JSON.stringify(
          {
            mode: modeLabel,
            profile,
            stats: serializableStats(derived),
          },
          null,
          2
        )
      );
    } else {
      renderStatsOnly(profile, derived, modeLabel);
    }
    return;
  }

  // --unique mode: hash stats directly into a seed (no DB lookup)
  if (args.unique) {
    const apiResult = await tryApiGenerate(derived, "unique");
    const seed = apiResult ? apiResult.seed : generateUniqueSeed(derived);
    const compat = isBedrockSafe(seed) ? "Java & Bedrock" : "Java only";
    const { share_text, gallery_url } = makeShareCard(
      seed,
      "UNIQUE",
      derived,
      null,
      true
    );
    if (args.json) {
      console.log(
        JSON.stringify(
          {
            seed,
            spawn_biome: "unknown (discover it!)",
            spawn_biome_display: "UNIQUE",
            spawn_x: "?",
            spawn_z: "?",
            compatibility: compat,
            chunkbase_url: `https://www.chunkbase.com/apps/seed-map#${seed}`,
            share_text,
            gallery_url,
            mode: modeLabel + " [unique]",
            stats: serializableStats(derived),
            unique: true,
          },
          null,
          2
        )
      );
    } else {
      console.log();
      console.log(`  Unique Seed: ${seed}  [${compat}]`);
      console.log();
      console.log("  Generated by hashing all your Claude Code stats.");
      console.log("  This seed is 100% unique to your exact usage.");
      console.log("  Biome: discover it in Minecraft or on Chunkbase!");
      console.log();
      console.log(
        `  Preview: https://www.chunkbase.com/apps/seed-map#${seed}`
      );
      console.log();
      console.log(`  ${share_text}`);
      console.log();
    }
    return;
  }

  // Default: biome-matched seed selection via API
  const apiResult = await tryApiGenerate(derived, "curated");

  if (apiResult && apiResult.seed !== undefined && apiResult.spawn_biome) {
    // API succeeded
    const seed = apiResult.seed;
    const spawnBiome = apiResult.spawn_biome;
    const spawnBiomeDisplay =
      apiResult.spawn_biome_display ??
      BIOME_LABELS[spawnBiome] ??
      spawnBiome.toUpperCase().replace(/_/g, " ");
    const spawnX = apiResult.spawn_x ?? 0;
    const spawnZ = apiResult.spawn_z ?? 0;
    const compat = apiResult.compatibility ??
      (isBedrockSafe(seed) ? "Java & Bedrock" : "Java only");
    const biomeTier = apiResult.biome_tier;
    const archetype = apiResult.archetype as { id: string; name: string; tagline: string } | undefined;

    // Use API profile if available, otherwise use computed profile
    if (apiResult.profile) {
      for (const k of Object.keys(apiResult.profile) as (keyof ClimateProfile)[]) {
        if (k in profile && apiResult.profile[k] !== undefined) {
          (profile as any)[k] = apiResult.profile[k]!;
        }
      }
    }

    const { share_text, gallery_url } = makeShareCard(
      seed,
      spawnBiomeDisplay,
      derived,
      profile
    );

    if (args.json) {
      console.log(
        JSON.stringify(
          {
            seed,
            spawn_biome: spawnBiome,
            spawn_biome_display: spawnBiomeDisplay,
            spawn_x: spawnX,
            spawn_z: spawnZ,
            compatibility: compat,
            chunkbase_url:
              apiResult.chunkbase_url ??
              `https://www.chunkbase.com/apps/seed-map#${seed}`,
            profile,
            biome_tier: biomeTier,
            archetype: archetype ?? null,
            stats: serializableStats(derived),
            gallery_url,
            mode: modeLabel,
          },
          null,
          2
        )
      );
    } else {
      renderOutput(
        { seed, spawn_biome: spawnBiome, spawn_x: spawnX, spawn_z: spawnZ },
        profile,
        derived,
        modeLabel
      );
    }
  } else {
    // API failed — output an error JSON
    if (args.json) {
      console.log(
        JSON.stringify(
          {
            error:
              "SeedCraft API unavailable. Could not generate seed.",
            profile,
            stats: serializableStats(derived),
            mode: modeLabel,
          },
          null,
          2
        )
      );
    } else {
      process.stderr.write(
        "Error: SeedCraft API is unavailable. Could not generate seed.\n"
      );
      process.stderr.write("Showing stats only:\n\n");
      renderStatsOnly(profile, derived, modeLabel);
    }
  }
}

main().catch((err) => {
  process.stderr.write(`Fatal error: ${err}\n`);
  process.exit(1);
});
