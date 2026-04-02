# Contributing to SeedCraft

Thanks for your interest! Here are ways to contribute:

## Easy contributions

- **Add narrative templates** — See `BIOME_NARRATIVES` in `scripts/generate_seed.ts`. Each biome has a short text that explains *why* the user got that world. Some biomes still use the generic fallback. Write a better one!
- **Expand the seed database** — Run `cd tools && make && make db` to generate more seeds, then merge them into `data/seeds_db.json`. More seeds = more unique worlds.

## Medium contributions

- **Add new climate mappings** — The `error_rate` and `night_ratio` stats are computed but unused. Have an idea for mapping them to a Minecraft parameter? Open an issue to discuss.
- **Localization** — Translate narrative templates to other languages.

## Project layout

This is a Claude Code **plugin** using the official plugin format:

```
.claude-plugin/plugin.json          # Plugin manifest (name, version)
skills/seedcraft/SKILL.md           # Skill instructions (what Claude does)
scripts/generate_seed.ts            # Main TypeScript script (zero dependencies)
data/seeds_db.json                  # Curated seed database (local fallback)
```

Users install with `/plugin marketplace add syaor4n/seedcraft`.

## Development setup

```bash
git clone https://github.com/syaor4n/seedcraft.git
cd seedcraft
node --experimental-strip-types scripts/generate_seed.ts --list  # Verify it works
```

No dependencies to install. Just Node.js 22+.

## Guidelines

- If you change the climate profile or selection algorithm, verify with `--all` on real data
- New narrative templates should reference the user's stats — never make static claims about the biome being "dry" or "cold" since the user's actual profile might contradict that
- The seed database JSON should stay compact (no indentation) to keep the plugin size reasonable
- Bump the `version` in `.claude-plugin/plugin.json` when making changes

## Regenerating the seed database

```bash
cd tools
make          # Clones cubiomes + compiles
make db       # Generates 1000 seeds -> ../data/seeds_db.json
```
