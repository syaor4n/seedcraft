# Contributing to codecraft-seed

Thanks for your interest! Here are ways to contribute:

## Easy contributions

- **Add narrative templates** — See `BIOME_NARRATIVES` in `scripts/generate_seed.py`. Each biome has a short text that explains *why* the user got that world. Some biomes still use the generic fallback. Write a better one!
- **Expand the seed database** — Run `cd tools && make && make db` to generate more seeds, then merge them into `data/seeds_db.json`. More seeds = more unique worlds.
- **Improve pretty_project_name** — The function that converts Claude Code project directory names to readable names. If it misparses yours, submit a fix with a test case.

## Medium contributions

- **Add new climate mappings** — The `error_rate` and `night_ratio` stats are computed but unused. Have an idea for mapping them to a Minecraft parameter? Open an issue to discuss.
- **Build a web UI** — A webpage where users can paste their `--json` output and see a visual world preview.
- **Localization** — Translate narrative templates to other languages.

## Project layout

This is a Claude Code **plugin** using the official plugin format:

```
.claude-plugin/plugin.json     # Plugin manifest (name, version)
skills/codecraft-seed/SKILL.md # Skill instructions (what Claude does)
scripts/generate_seed.py       # Main Python script
data/seeds_db.json             # Curated seed database
```

Users install with `/plugin add syaor4n/codecraft-seed`.

## Development setup

```bash
git clone https://github.com/syaor4n/codecraft-seed.git
cd codecraft-seed
python3 -m unittest tests.test_generate_seed -v  # Run tests
```

No dependencies to install. Just Python 3.9+.

## Guidelines

- Run `python3 -m unittest tests.test_generate_seed` before submitting — all 108 tests must pass
- If you change the climate profile or selection algorithm, verify with `--all` on real data
- New narrative templates should reference the user's stats (use `{messages}`, `{tool_calls}`, `{hours:.0f}`, etc.) — never make static claims about the biome being "dry" or "cold" since the user's actual profile might contradict that
- The seed database JSON should stay compact (no indentation) to keep the plugin size reasonable
- Bump the `version` in `.claude-plugin/plugin.json` when making changes

## Regenerating the seed database

```bash
cd tools
make          # Clones cubiomes + compiles
make db       # Generates 1000 seeds -> ../data/seeds_db.json
```

The shipped database was built by merging multiple runs with different LCG seeds for maximum coverage:

```bash
./analyze_seeds 1000 1 > /tmp/batch1.json
./analyze_seeds 1000 2 > /tmp/batch2.json
./analyze_seeds 1000 3 > /tmp/batch3.json
# Then merge with a script, deduplicate by seed value, remove "unknown" biomes
```

The second argument seeds the LCG random generator (not the Minecraft seed itself), producing different random distributions each time.
