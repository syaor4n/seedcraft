---
name: craft
description: >
  Converts Claude Code usage statistics into a Minecraft world seed with
  real biome correlation. Maps coding behavior to Minecraft climate parameters
  (messages=temperature, tools=humidity, session duration=elevation, etc.)
  and selects a curated seed whose spawn biome genuinely matches the profile.
  Use when the user mentions "minecraft seed", "generate a seed", "claude to
  minecraft", "what's my minecraft world", "seed from my stats", or any
  variation of turning Claude Code usage into a Minecraft world seed.
---

# SeedCraft

Converts Claude Code usage statistics into a Minecraft world seed with **real
biome correlation** — the generated world's spawn biome genuinely reflects
your coding behavior.

**Web companion:** [seedcraft.dev](https://seedcraft.dev) — browse the community gallery, explore biome tiers, and share your world.

## How it works

1. Reads session data from `~/.claude/projects/` (JSONL conversation files)
2. Extracts rich stats: messages, tool calls by category, session durations,
   project count, write/edit volume, error rates, agent usage, and more
3. Maps stats to a **Minecraft climate profile**:
   - More messages = hotter world (Temperature)
   - More tool calls = lusher vegetation (Humidity)
   - Longer total session time = taller mountains (Elevation/Erosion)
   - More projects = more biome diversity
   - More write/edit calls = more continental (less ocean)
   - More unique tools = weirder terrain
   - More agent calls = more structures/villages
4. Calls the **SeedCraft API** (seedcraft.dev) for matching against **500,000 curated seeds**.
   If the API is unreachable, falls back to a local database of 7,090 seeds.
   Uses two-stage biome selection: first finds the correct biome, then
   the best individual seed within that biome
5. Outputs the seed, a visual climate card, and a biome-specific narrative

## Usage

### Steps

1. **If the user's intent is NOT already clear**, use AskUserQuestion to ask what they want:

   Question: "What Minecraft seed would you like to generate?"
   Options:
   - **Current project** — Seed from your current project ({detect CWD project name})
   - **All projects** — Seed combining all your Claude Code activity
   - **Unique seed** — 100% unique seed hashed from your stats (biome is a surprise!)
   - *(User can also type a specific project name via "Other")*

   Skip this question if the user already specified what they want (e.g. "generate for all", "unique seed", "seed for my-api").

2. Run the script with `--json` based on the user's choice:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_seed.py --json                           # Current project (auto-detect CWD)
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_seed.py --all --json                     # All projects
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_seed.py --all --unique --json            # Unique seed (all)
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_seed.py --unique --json                  # Unique seed (current project)
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_seed.py --project "name" --json          # Specific project
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/generate_seed.py --list                           # List projects
   ```
   `${CLAUDE_PLUGIN_ROOT}` is automatically resolved by Claude Code to the plugin's install directory.

   **Note:** Requires Python 3.9+. If `python3` is not available, try `python`.

3. Format and present the JSON result to the user as a rich message.

   **For default (biome-matched) mode** — use the JSON fields to build:

   ```
   ## Your Minecraft Seed: `{seed}`

   **Biome: {spawn_biome_display}** — Spawn at ({spawn_x}, {spawn_z}) [{compatibility}]

   ### Climate Profile
   | Parameter | Value | Label |
   |---|---|---|
   | Temperature | {temperature}% | {label} |
   | Humidity | {humidity}% | {label} |
   | Elevation | {100 - erosion}% | {label} |
   | Continental | {continentalness}% | {label} |
   | Weirdness | {weirdness}% | {label} |

   ### Stats
   - **Messages:** {messages} ({human} you / {assistant} AI)
   - **Tool calls:** {tool_calls} ({unique_tools} unique)
   - **Active time:** {hours}h ({sessions} sessions)
   - **Top tools:** {top_tools list}

   ### Links
   - Paste `{seed}` in Minecraft > Create New World > Seed
   - Preview: [Chunkbase map]({chunkbase_url})
   - Works on Java & Bedrock 1.18+
   ```

   **For unique mode** (JSON has `"unique": true`) — do NOT show Climate Profile (it has no relation to the unique seed). Show:

   ```
   ## Your Unique Minecraft Seed: `{seed}`

   This seed is 100% unique — hashed from all your Claude Code stats. [{compatibility}]

   ### Stats
   - **Messages:** {messages} ({human} you / {assistant} AI)
   - **Tool calls:** {tool_calls} ({unique_tools} unique)
   - **Active time:** {hours}h ({sessions} sessions)
   - **Top tools:** {top_tools list}

   ### Links
   - Paste `{seed}` in Minecraft > Create New World > Seed
   - Preview: [Chunkbase map]({chunkbase_url}) — discover your biome!
   - Works on Java & Bedrock 1.18+
   ```

4. After presenting the result, always include the **share card** at the end:

   ```
   ---
   **Share your world:**
   - [Add to gallery]({gallery_url}) — this will generate a unique 3D voxel terrain from your climate profile
   ```

   The `gallery_url` opens seedcraft.dev/gallery with seed, climate params, and stats pre-filled. When the user submits, a personalized 3D voxel terrain is rendered and captured as a thumbnail.

5. If the user asks what the seed "means" or wants to explore:
   - Paste it into Minecraft directly (Java or Bedrock 1.18+)
   - Preview on Chunkbase: `chunkbase.com/apps/seed-map#<seed>`
   - The spawn biome genuinely matches their coding profile

## Climate mapping reference

| Stat                  | MC Parameter       | Effect                                |
|-----------------------|--------------------|---------------------------------------|
| Message count         | Temperature        | More messages = hotter world          |
| Total tool calls      | Humidity           | More tools = lusher, more humid       |
| Total session time    | Erosion (inv)      | More time = taller mountains          |
| Write/Edit calls      | Continentalness    | More building = more land, less ocean |
| Unique tools          | Weirdness          | More diverse tools = stranger terrain |
| Agent calls           | Structure density  | More agents = more villages           |
| Project count         | Biome diversity    | More projects = more varied biomes    |

## Technical notes

- Calls the SeedCraft API (seedcraft.dev) with 8 aggregated numbers for matching against 500,000 seeds
- If the API is unreachable (offline, timeout >5s), falls back to a local database of 7,090 seeds
- Two-stage selection: biome center matching, then individual seed matching
- Each seed's spawn biome and climate parameters are verified at the block level
- Selection uses weighted Euclidean distance on 5 core climate parameters
- A SHA-256 fingerprint of the user's stats provides deterministic tiebreaking
- Same stats always produce the same seed (deterministic)
- Includes subagent sessions (often 99% of Claude Code activity)
- Works on Java & Bedrock 1.18+ (identical terrain generation)

## Privacy

The API call sends **only 8 aggregated numbers**: messages, tool_calls, write_calls,
total_active_hours, unique_tools, agent_calls, orchestrate_calls, project_count.
No code, no file names, no project names, no conversation content. If the API is
unreachable, everything works offline. No telemetry, no tracking, no account required.
