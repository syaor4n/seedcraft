<div align="center">

# SeedCraft

### Your code. Your world.

Your [Claude Code](https://claude.ai/claude-code) stats create a unique Minecraft world.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Node.js 22+](https://img.shields.io/badge/Node.js-22%2B-339933.svg)](https://nodejs.org)
[![MC 1.21+](https://img.shields.io/badge/Minecraft-1.21%2B-62B47A.svg)](https://minecraft.wiki)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-ffdd00?logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/syaor4n)
[![Web](https://img.shields.io/badge/Web-seedcraft.dev-DA7756)](https://seedcraft.dev)

![SeedCraft demo](assets/demo.gif)

**More messages = hotter biome. More tools = denser jungle. More hours = taller peaks.**

[Quick Start](#quick-start) | [How It Works](#how-your-coding-shapes-the-world) | [Biome Tiers](#biome-rarity-tiers) | [Gallery](https://seedcraft.dev/gallery) | [Share Your World](#share-your-world)

</div>

---

The more you code, the more your world evolves — heavy projects produce scorching badlands, marathon sessions raise jagged peaks, and diverse tool usage warps the terrain into alien landscapes.

Your world is selected from a curated database of **500,000 real Minecraft seeds** analyzed with [Cubiomes](https://github.com/Cubitect/cubiomes) across **46 biomes**, ensuring the spawn biome **genuinely matches** your coding profile. Paste the seed into Minecraft and discover the world your code created.

### Your Minecraft World: `-233730394`

**Biome: Wooded Badlands** — Spawn at (-608, 112) [Java & Bedrock]

#### Climate Profile

| Parameter | Value | Label |
|---|---|---|
| Temperature | 89% | Hot |
| Humidity | 79% | Tropical |
| Elevation | 85% | Jagged Peaks |
| Continental | 84% | Far Inland |
| Weirdness | 78% | Bizarre |

#### Stats (all projects)

- **Messages:** 260,397 (107,550 you / 152,847 AI)
- **Tool calls:** 99,713 (79 unique tools)
- **Active time:** 561h (2,869 sessions)
- **Top tools:** Read (36,563), Bash (21,227), Edit (14,087)

**Preview:** [Chunkbase map](https://www.chunkbase.com/apps/seed-map#-233730394) | Deterministic: same stats = same world.

## Quick start

### Install as a Claude Code plugin (recommended)

In Claude Code, run:

```
/plugin marketplace add syaor4n/seedcraft
/plugin install seedcraft@seedcraft
```

That's it. Type `/craft` to discover your Minecraft world.

The plugin auto-updates when you restart Claude Code.

### Install from local clone

```bash
git clone https://github.com/syaor4n/seedcraft.git
```

Then in Claude Code:

```
/plugin marketplace add /path/to/seedcraft
/plugin install seedcraft@seedcraft
```

### Standalone (no Claude Code needed)

```bash
git clone https://github.com/syaor4n/seedcraft.git
cd seedcraft
node --experimental-strip-types scripts/generate_seed.ts --all
```

Only requires Node.js 22+. No npm install, no dependencies.

## How your coding shapes the world

Minecraft 1.18+ generates biomes using 6 climate parameters (temperature, humidity, continentalness, erosion, weirdness, depth). SeedCraft maps your Claude Code stats to these exact parameters, then finds a real seed whose spawn matches.

| What you do in Claude Code | What happens in Minecraft | Example |
|---|---|---|
| Send lots of messages | World gets **hotter** | 100K+ messages = desert, badlands |
| Use lots of tools (Read, Edit, Bash...) | Vegetation gets **denser** | 50K+ messages + 30K+ tools = jungle |
| Code for many hours | Mountains get **taller** | 300h+ = jagged peaks, frozen peaks |
| Write & edit files frequently | More **land**, less ocean | 10K+ edits = far inland, continental |
| Use many different tools | Terrain gets **stranger** | 70+ unique tools = ice spikes, cherry grove |
| Delegate to subagents | **Structures** bar goes up | Visible in your climate profile card |
| Work across many projects | **Diversity** bar goes up | Visible in your climate profile card |

The output ranges are calibrated to Minecraft's actual biome parameter space. A user with zero messages doesn't get "absolute zero" — they get a cold-but-real biome like snowy plains.

## Usage

### Skill commands

```
/craft                     # World from your current project (auto-detected from CWD)
/craft all                 # World from all your projects combined
/craft my-api              # World from a specific project
/craft unique              # 100% unique world hashed from your stats (biome is a surprise!)
/craft --list              # See all your projects
```

The skill also triggers on natural phrases like *"create my minecraft world"* or *"what's my minecraft world"*.

### Two modes

| Mode | What it does | Best for |
|---|---|---|
| **Default** (curated) | Creates your world from 500,000 pre-analyzed seeds across 46 biomes. Spawn biome is known and matches your coding profile. | Seeing how your coding style shapes a Minecraft world |
| **Unique** (`--unique`) | SHA-256 hashes all your stats into a one-of-a-kind world. Biome is unknown — discover it! | Getting a world that's truly yours and only yours |

### Standalone CLI

```bash
node --experimental-strip-types scripts/generate_seed.ts                     # Current project (auto-detect CWD)
node --experimental-strip-types scripts/generate_seed.ts --all               # All projects combined
node --experimental-strip-types scripts/generate_seed.ts --project "my-api"  # Specific project
node --experimental-strip-types scripts/generate_seed.ts --unique            # Unique hash-based seed
node --experimental-strip-types scripts/generate_seed.ts --all --unique      # Unique seed from all projects
node --experimental-strip-types scripts/generate_seed.ts --list              # List projects
node --experimental-strip-types scripts/generate_seed.ts --all --stats-only  # Climate profile only
node --experimental-strip-types scripts/generate_seed.ts --all --json        # JSON output
```

Fuzzy matching is supported: `--project dashboard` matches `dashboard-v2`, `admin-dashboard`, etc.

## Loading your world in Minecraft

### Java Edition

1. Open Minecraft Java Edition
2. Click **Singleplayer** > **Create New World**
3. Click **More World Options...**
4. Paste your seed number in the **Seed for the World Generator** field
5. Click **Create New World**

To verify: type `/seed` in the chat (works without cheats in Java singleplayer).

### Bedrock Edition (Windows 10, Xbox, PlayStation, Switch, Mobile)

1. Open Minecraft > **Play** > **Create New**
2. Tap **Create New World**
3. Expand the **Advanced** section
4. Paste your seed number in the **Seed** field
5. Tap **Create**

> **Note:** Bedrock Edition uses 32-bit seeds. SeedCraft prefers Bedrock-compatible seeds (shown as `[Java & Bedrock]` in the output). Seeds marked `[Java only]` will generate a different world on Bedrock.

### Preview on Chunkbase (no Minecraft needed)

The output includes a [Chunkbase](https://www.chunkbase.com/apps/seed-map) link. Open it in any browser to:

1. See the full world map with all biomes color-coded
2. Find villages, temples, strongholds, and other structures
3. Locate your spawn point and plan your first base
4. Toggle specific biomes or structures with the **Features** panel

Make sure to select **Java** or **Bedrock** and the correct Minecraft version (1.21+) in Chunkbase for accurate results.

## Examples

| Coding style | Biome | Why |
|---|---|---|
| **The marathon coder** — 175K messages, 67K tools, 385 hours | Wooded Badlands | Scorching heat from messages, towering mesas from marathon sessions |
| **The team lead** — 55K messages, 20K tools, 110 hours | Wooded Badlands | Hot, humid, deep inland — intense multi-session leadership |
| **The builder** — 18K messages, 7K tools, 52 hours | Stony Shore | Moderate warmth meets the rocky coast |
| **The explorer** — 2.7K messages, 1K tools, read-heavy | Beach | Warm but few writes — the coastline of curiosity |
| **The weekend hacker** — 1.4K messages, 3 hours | Snowy Plains | A quiet, pristine world waiting for footprints |

## Biome rarity tiers

Not all worlds are equally easy to unlock. Your coding intensity determines which tier you reach.

**Common** — Most developers start here
> Plains, Forest, Savanna

**Uncommon** — Regular Claude Code users
> Old Growth Birch Forest, Birch Forest, Snowy Taiga, Dripstone Caves, Desert, Snowy Plains, Taiga

**Rare** — Power users with significant projects
> Stony Shore, Sparse Jungle, Beach, Dark Forest, Jungle

**Epic** — Heavy long-term users only
> Mangrove Swamp, Grove, Lush Caves, Badlands, Old Growth Pine Taiga, Old Growth Spruce Taiga, Bamboo Jungle, Sunflower Plains, Flower Forest, Swamp

**Legendary** — Extreme stats required (< 5% of seeds)
> Warm Ocean, Lukewarm Ocean, Cold Ocean, Ocean, Pale Garden, Frozen Ocean, Stony Peaks, Jagged Peaks, Frozen Peaks, Cherry Grove, Windswept Forest, Savanna Plateau, Windswept Hills, Ice Spikes, Eroded Badlands, Snowy Beach, Snowy Slopes, Windswept Savanna, Wooded Badlands, Meadow (if you get one of these, you've earned bragging rights)

## seedcraft.dev

The web companion for SeedCraft: **[seedcraft.dev](https://seedcraft.dev)**

- **Interactive demo** — see how coding stats map to Minecraft climate parameters with live sliders
- **Community gallery** — browse and share worlds generated by other developers ([seedcraft.dev/gallery](https://seedcraft.dev/gallery))
- **500K seed database** — the skill calls the API for matching against 500,000 curated seeds (with local fallback if offline)
- **Biome tiers** — discover which biomes are common, rare, and legendary

The skill automatically calls the seedcraft.dev API when online. If the API is unreachable, it falls back to the local 7K seed database — everything still works offline.

## Share your world

Got your world? We want to see it.

- **Share on the gallery** — go to [seedcraft.dev/gallery](https://seedcraft.dev/gallery) and submit your seed with a comment
- **Post on X/Twitter** with `#SeedCraft`
- **Open the Chunkbase link**, screenshot the map, and share your world
- **Load the seed in Minecraft**, take a screenshot at spawn, and show your biome
- **Compare with friends** — who has the rarest world? Who codes in a jungle?

## How it works (technical)

### 1. Stat extraction

Reads all JSONL session data from `~/.claude/projects/`, including subagent sessions (which often represent 99% of Claude Code activity). Extracts messages, tool calls by category, session durations, unique tool diversity, write/edit volume, error rates, model usage, and more.

### 2. Climate profile

Maps each stat to a Minecraft climate parameter using piecewise linear interpolation with breakpoints calibrated to MC's actual biome parameter space:

| Stat | MC parameter | Breakpoints (input -> output) |
|---|---|---|
| Messages | Temperature | 0 -> 0.15 ... 500K -> 0.92 |
| Tool calls | Humidity | 0 -> 0.25 ... 200K -> 0.82 |
| Write calls | Continentalness | 0 -> 0.40 ... 30K -> 0.88 |
| Active hours | Erosion (inv.) | 0h -> 0.82 ... 500h -> 0.15 |
| Unique tools | Weirdness | 0 -> 0.15 ... 120 -> 0.85 |

### 3. Two-stage seed selection (default mode)

1. **Biome matching** — Computes weighted Euclidean distance from your profile to the average climate center of each of the 46 biome types. The closest biome wins.
2. **Seed selection** — Among all seeds of the winning biome, finds the closest individual match. Prefers Bedrock-compatible (32-bit) seeds.
3. **Deterministic tiebreak** — SHA-256 hash of your stats picks among the top-20 closest seeds. Same stats always produce the same seed.

This two-stage approach guarantees the biome is always the conceptually correct one. The hash only varies the specific seed, never the biome.

### 3b. Unique seed generation (`--unique` mode)

Hashes 16 stat dimensions (messages, human/assistant counts, tool calls, unique tools, total chars, project names, session count, active time, errors, agent calls, read/write/execute calls, MCP calls, models) via SHA-256 into a single 32-bit signed integer. Completely unique to your exact usage. Biome is unknown — discover it in-game or on Chunkbase.

### 4. Seed database

`data/seeds_db.json` contains 500,000 seeds analyzed with [Cubiomes](https://github.com/Cubitect/cubiomes) for Minecraft 1.21. Each seed has its spawn biome verified at block scale with 5 climate noise parameters and a biome diversity score. 46 of the 51 spawnable overworld biomes are represented.

To regenerate or expand:

```bash
cd tools
make       # Clones Cubiomes + compiles the analyzer
make db    # Generates seeds -> ../data/seeds_db.json
```

## FAQ

**Is the seed random?**
No. The same stats always produce the same seed. Your seed only changes when your Claude Code usage changes (new messages, new sessions, new projects). In default mode, the seed is picked from a curated database (biome-matched). In `--unique` mode, it's a SHA-256 hash of all your stats — guaranteed unique to your exact usage.

**Will my seed change every time I code?**
Yes, slightly — each new message adjusts your stats. If you want to "lock in" a seed, save it somewhere. The changes are gradual: one extra message won't jump you from jungle to desert.

**Does it work on Bedrock?**
Yes. SeedCraft generates **32-bit seeds** (range −2,147,483,648 to 2,147,483,647) which work on both Java and Bedrock. Since Minecraft 1.18, both editions generate the same **terrain and biomes** from the same seed. Structures (villages, temples, strongholds) will be in different locations between editions.

**Why not 64-bit seeds like `8150810962987124925`?**
Minecraft Java Edition supports 64-bit seeds (18.4 quintillion possibilities), while Bedrock only supports 32-bit (4.3 billion). SeedCraft deliberately uses 32-bit seeds so your world works on **every platform** — Java, Bedrock, Windows, Xbox, PlayStation, Switch, iOS, Android. With 500,000 curated seeds across 46 biomes, the 32-bit range provides more than enough diversity for precise biome matching. The terrain and biome generation is identical regardless of seed size — a 32-bit seed produces worlds just as rich as a 64-bit one.

**What Minecraft version should I use?**
1.18 or later. The seed database was analyzed for 1.21, but all 1.18+ versions use the same multi-noise biome system.

**Is my data sent anywhere?**
When using the skill, a single API call is made to our server with **8 aggregated numbers only**: messages, tool_calls, write_calls, total_active_hours, unique_tools, agent_calls, orchestrate_calls, and project_count. No code, no file names, no project names, no conversation content — just 8 counters. This lets us match your profile against the full 500,000-seed database hosted on our server. If the API is unreachable, the skill falls back to a local computation using a smaller embedded seed database — everything still works offline. No telemetry, no tracking, no account required.

**Can I preview my world without Minecraft?**
Yes. The output includes a Chunkbase link: `chunkbase.com/apps/seed-map#<your-seed>`. Open it in a browser to see the full world map.

**I got snowy_plains. Is that boring?**
It means your project is young or small. Code more and watch your world evolve. Even snowy plains have their charm — track your progress as the biome transforms from frozen tundra to scorching badlands.

**How accurate is the biome prediction?**
Very. The two-stage selection guarantees the seed's spawn biome matches the closest biome center to your profile. We verified this against 500,000 real seeds analyzed with the same biome algorithm Minecraft uses internally.

## Running tests

Tests for the TypeScript CLI are planned. The seed matching logic is server-side (seedcraft.dev API).

## Project structure

```
seedcraft/
├── .claude-plugin/
│   └── plugin.json            # Plugin manifest (name, version, author)
├── skills/
│   └── seedcraft/
│       └── SKILL.md           # Skill definition (instructions for Claude)
├── scripts/
│   └── generate_seed.ts       # Main script (TypeScript, zero dependencies)
├── data/
│   └── seeds_db.json          # 500,000 curated seeds (local fallback)
├── tools/
│   ├── analyze_seeds.c        # Cubiomes seed analyzer
│   └── Makefile
├── LICENSE                    # MIT
└── README.md
```

## How Minecraft biomes work

Minecraft 1.18+ places biomes using a [multi-noise system](https://minecraft.wiki/w/Biome#Overworld). At every block column, 6 Perlin noise values determine the biome:

| Parameter | What it controls |
|---|---|
| Temperature | Hot (desert, jungle, badlands) vs cold (snowy plains, frozen peaks) |
| Humidity | Lush (jungle, dark forest, swamp) vs dry (desert, savanna, badlands) |
| Continentalness | Ocean and coast vs deep inland |
| Erosion | Flat (plains, swamp) vs mountainous (peaks, slopes) |
| Weirdness | Normal vs unusual terrain (rare biome variants) |
| Depth | Surface biomes vs cave biomes (dripstone, lush caves) |

The world seed feeds these noise generators. Same seed = same world, always.

## License

[MIT](LICENSE)
