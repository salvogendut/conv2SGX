SALV = ../rasm/salvador/src
LZSA = ../rasm/lzsa-master/src
APU  = ../rasm/apultra-master/src

# Strip scc Z80 tools from PATH so system gcc/as/ld are used
export PATH := /usr/local/bin:/usr/bin:/bin

CC = gcc
CFLAGS = -O2 -I$(SALV) -I$(LZSA)/libdivsufsort/include

SALV_OBJ = $(SALV)/shrink.o $(SALV)/matchfinder.o $(SALV)/expand.o
APU_OBJ  = $(APU)/libdivsufsort/lib/divsufsort.o \
           $(APU)/libdivsufsort/lib/divsufsort_utils.o \
           $(APU)/libdivsufsort/lib/sssort.o \
           $(APU)/libdivsufsort/lib/trsort.o

.PHONY: all clean

all: zx0tool

zx0tool: zx0tool.o
	$(CC) $< $(SALV_OBJ) $(APU_OBJ) -lm -o $@

zx0tool.o: zx0tool.c
	$(CC) -c $(CFLAGS) $< -o $@

clean:
	rm -f zx0tool zx0tool.o
