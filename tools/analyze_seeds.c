/*
 * Cubiomes-based Minecraft Seed Analyzer
 *
 * Generates a curated database of seeds with known spawn biome and
 * climate parameters at spawn. Outputs JSON to stdout.
 *
 * Compile:
 *   cc -O3 -o analyze_seeds analyze_seeds.c cubiomes/generator.c \
 *      cubiomes/biomenoise.c cubiomes/biomes.c cubiomes/layers.c \
 *      cubiomes/noise.c cubiomes/finders.c -lm
 *
 * Usage:
 *   ./analyze_seeds <count> [start_seed]
 *   ./analyze_seeds 1000            # analyze 1000 random seeds
 *   ./analyze_seeds 500 12345       # start from seed 12345
 */

#include "cubiomes/generator.h"
#include "cubiomes/finders.h"
#include "cubiomes/biomenoise.h"
#include "cubiomes/biomes.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <stdint.h>

/* -------------------------------------------------------------------
 * Biome name table
 * ------------------------------------------------------------------- */
typedef struct { int id; const char *name; } BiomeName;

static const BiomeName BIOME_NAMES[] = {
    { ocean,                "ocean" },
    { plains,               "plains" },
    { desert,               "desert" },
    { windswept_hills,      "windswept_hills" },
    { forest,               "forest" },
    { taiga,                "taiga" },
    { swamp,                "swamp" },
    { river,                "river" },
    { frozen_ocean,         "frozen_ocean" },
    { frozen_river,         "frozen_river" },
    { snowy_plains,         "snowy_plains" },
    { mushroom_fields,      "mushroom_fields" },
    { beach,                "beach" },
    { jungle,               "jungle" },
    { sparse_jungle,        "sparse_jungle" },
    { deep_ocean,           "deep_ocean" },
    { stony_shore,          "stony_shore" },
    { snowy_beach,          "snowy_beach" },
    { birch_forest,         "birch_forest" },
    { dark_forest,          "dark_forest" },
    { snowy_taiga,          "snowy_taiga" },
    { old_growth_pine_taiga,"old_growth_pine_taiga" },
    { old_growth_spruce_taiga, "old_growth_spruce_taiga" },
    { windswept_forest,     "windswept_forest" },
    { savanna,              "savanna" },
    { savanna_plateau,      "savanna_plateau" },
    { badlands,             "badlands" },
    { wooded_badlands,      "wooded_badlands" },
    { warm_ocean,           "warm_ocean" },
    { lukewarm_ocean,       "lukewarm_ocean" },
    { cold_ocean,           "cold_ocean" },
    { deep_warm_ocean,      "deep_warm_ocean" },
    { deep_lukewarm_ocean,  "deep_lukewarm_ocean" },
    { deep_cold_ocean,      "deep_cold_ocean" },
    { deep_frozen_ocean,    "deep_frozen_ocean" },
    { sunflower_plains,     "sunflower_plains" },
    { flower_forest,        "flower_forest" },
    { ice_spikes,           "ice_spikes" },
    { old_growth_birch_forest, "old_growth_birch_forest" },
    { windswept_savanna,    "windswept_savanna" },
    { eroded_badlands,      "eroded_badlands" },
    { bamboo_jungle,        "bamboo_jungle" },
    { meadow,               "meadow" },
    { grove,                "grove" },
    { snowy_slopes,         "snowy_slopes" },
    { jagged_peaks,         "jagged_peaks" },
    { frozen_peaks,         "frozen_peaks" },
    { stony_peaks,          "stony_peaks" },
    { mangrove_swamp,       "mangrove_swamp" },
    { cherry_grove,         "cherry_grove" },
    { pale_garden,          "pale_garden" },
    { dripstone_caves,      "dripstone_caves" },
    { lush_caves,           "lush_caves" },
    { 0, NULL }
};

static const char *biome_name(int id)
{
    for (int i = 0; BIOME_NAMES[i].name; i++) {
        if (BIOME_NAMES[i].id == id)
            return BIOME_NAMES[i].name;
    }
    return "unknown";
}

/* -------------------------------------------------------------------
 * Normalize noise parameter from internal int64 to 0.0-1.0 range.
 * Cubiomes stores noise params as fixed-point: value * 10000.
 * The actual range is roughly -1.0 to 1.0, so we map to 0.0-1.0.
 * ------------------------------------------------------------------- */
static double norm_np(int64_t raw)
{
    double v = (double)raw / 10000.0;
    /* Clamp to [-1, 1] then map to [0, 1] */
    if (v < -1.0) v = -1.0;
    if (v >  1.0) v =  1.0;
    return (v + 1.0) / 2.0;
}

/* -------------------------------------------------------------------
 * Simple LCG for seed generation (fast, doesn't need to be crypto)
 * ------------------------------------------------------------------- */
static uint64_t lcg_state;

static void lcg_seed(uint64_t s) { lcg_state = s; }
static uint64_t lcg_next(void)
{
    lcg_state = lcg_state * 6364136223846793005ULL + 1442695040888963407ULL;
    return lcg_state;
}

/* -------------------------------------------------------------------
 * Analyze a single seed: get spawn biome + climate at spawn area
 * ------------------------------------------------------------------- */
typedef struct {
    int64_t seed;
    int spawn_biome;
    int spawn_x, spawn_z;
    double temperature;
    double humidity;
    double continentalness;
    double erosion;
    double weirdness;
    int biome_diversity;   /* unique biomes in 128x128 area around spawn */
} SeedInfo;

static int analyze_seed(Generator *g, int64_t seed, SeedInfo *info)
{
    applySeed(g, DIM_OVERWORLD, (uint64_t)seed);

    /* Get spawn point */
    Pos spawn = getSpawn(g);
    info->seed = seed;
    info->spawn_x = spawn.x;
    info->spawn_z = spawn.z;

    /* Get biome at spawn (block scale) */
    info->spawn_biome = getBiomeAt(g, 1, spawn.x, 64, spawn.z);
    if (info->spawn_biome < 0)
        return -1;

    /* Sample climate noise parameters at spawn (biome scale = 1:4) */
    int64_t np[6] = {0};
    sampleBiomeNoise(&g->bn, np, spawn.x >> 2, 16, spawn.z >> 2, NULL, 0);

    info->temperature     = norm_np(np[NP_TEMPERATURE]);
    info->humidity        = norm_np(np[NP_HUMIDITY]);
    info->continentalness = norm_np(np[NP_CONTINENTALNESS]);
    info->erosion         = norm_np(np[NP_EROSION]);
    info->weirdness       = norm_np(np[NP_WEIRDNESS]);

    /* Count unique biomes in 128x128 block area around spawn (at scale 4) */
    int seen[256] = {0};
    int unique = 0;
    int sx = (spawn.x - 64) >> 2;
    int sz = (spawn.z - 64) >> 2;
    for (int dz = 0; dz < 32; dz += 2) {
        for (int dx = 0; dx < 32; dx += 2) {
            int b = getBiomeAt(g, 4, sx + dx, 16, sz + dz);
            if (b >= 0 && b < 256 && !seen[b]) {
                seen[b] = 1;
                unique++;
            }
        }
    }
    info->biome_diversity = unique;

    return 0;
}

/* -------------------------------------------------------------------
 * Main: generate N seeds, analyze, output JSON
 * ------------------------------------------------------------------- */
int main(int argc, char *argv[])
{
    int count = 1000;
    int64_t start_seed = 0;
    int use_start = 0;

    if (argc >= 2)
        count = atoi(argv[1]);
    if (argc >= 3) {
        start_seed = atoll(argv[2]);
        use_start = 1;
    }
    if (count <= 0) {
        fprintf(stderr, "Usage: %s <count> [start_seed]\n", argv[0]);
        return 1;
    }

    /* Initialize generator for MC 1.21 */
    Generator g;
    setupGenerator(&g, MC_1_21, 0);

    /* Seed the LCG — start_seed controls reproducibility, not the MC seed range */
    lcg_seed(use_start ? (uint64_t)start_seed : (uint64_t)time(NULL) ^ 0xDEADBEEFCAFE);

    /* Output JSON header */
    printf("{\n");
    printf("  \"version\": \"1.21\",\n");
    printf("  \"mc_enum\": \"MC_1_21\",\n");
    printf("  \"count\": %d,\n", count);
    printf("  \"seeds\": [\n");

    int first = 1;
    int analyzed = 0;

    for (int i = 0; i < count * 3 && analyzed < count; i++) {
        /* Always use LCG for well-distributed seeds across the full range.
         * Clamp to 32-bit signed range for Bedrock compatibility. */
        int64_t seed = (int64_t)((int32_t)(lcg_next() >> 16));

        SeedInfo info;
        if (analyze_seed(&g, seed, &info) != 0)
            continue;

        /* Skip ocean/river seeds at spawn (not interesting) */
        int b = info.spawn_biome;
        if (b == river || b == frozen_river)
            continue;

        if (!first) printf(",\n");
        first = 0;

        printf("    {\n");
        printf("      \"seed\": %lld,\n", (long long)info.seed);
        printf("      \"spawn_biome\": \"%s\",\n", biome_name(info.spawn_biome));
        printf("      \"spawn_x\": %d,\n", info.spawn_x);
        printf("      \"spawn_z\": %d,\n", info.spawn_z);
        printf("      \"climate\": {\n");
        printf("        \"temperature\": %.4f,\n", info.temperature);
        printf("        \"humidity\": %.4f,\n", info.humidity);
        printf("        \"continentalness\": %.4f,\n", info.continentalness);
        printf("        \"erosion\": %.4f,\n", info.erosion);
        printf("        \"weirdness\": %.4f\n", info.weirdness);
        printf("      },\n");
        printf("      \"biome_diversity\": %d\n", info.biome_diversity);
        printf("    }");

        analyzed++;
    }

    printf("\n  ]\n");
    printf("}\n");

    fprintf(stderr, "Analyzed %d seeds for MC 1.21\n", analyzed);
    return 0;
}
