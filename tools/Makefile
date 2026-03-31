CC = cc
CFLAGS = -O3 -Wall
CUBIOMES = cubiomes

SRCS = analyze_seeds.c \
       $(CUBIOMES)/generator.c \
       $(CUBIOMES)/biomenoise.c \
       $(CUBIOMES)/biomes.c \
       $(CUBIOMES)/layers.c \
       $(CUBIOMES)/noise.c \
       $(CUBIOMES)/finders.c

TARGET = analyze_seeds

all: $(TARGET)

# Clone cubiomes if not present
$(CUBIOMES)/generator.c:
	git clone --depth 1 https://github.com/Cubitect/cubiomes.git $(CUBIOMES)

$(TARGET): $(CUBIOMES)/generator.c $(SRCS)
	$(CC) $(CFLAGS) -o $@ analyze_seeds.c $(CUBIOMES)/generator.c $(CUBIOMES)/biomenoise.c $(CUBIOMES)/biomes.c $(CUBIOMES)/layers.c $(CUBIOMES)/noise.c $(CUBIOMES)/finders.c -lm

clean:
	rm -f $(TARGET)

# Generate the seed database
# The shipped DB uses ~7,490 seeds from multiple runs merged together.
# A single run of 1000 is a good starting point.
db: $(TARGET)
	./$(TARGET) 1000 > ../data/seeds_db.json

.PHONY: all clean db
