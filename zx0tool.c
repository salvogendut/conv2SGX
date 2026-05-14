/* zx0tool.c - Compress stdin to stdout using ZX0 inverted (SymbOS format) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../rasm/salvador/src/libsalvador.h"

int main(void) {
    unsigned char *in = NULL;
    size_t in_size = 0, in_cap = 0;
    unsigned char buf[4096];
    size_t n;

    /* Read all of stdin */
    while ((n = fread(buf, 1, sizeof(buf), stdin)) > 0) {
        if (in_size + n > in_cap) {
            in_cap = in_cap ? in_cap * 2 : 65536;
            while (in_cap < in_size + n) in_cap *= 2;
            in = realloc(in, in_cap);
            if (!in) { fprintf(stderr, "out of memory\n"); return 1; }
        }
        memcpy(in + in_size, buf, n);
        in_size += n;
    }

    if (in_size == 0) return 0;

    size_t max_out = salvador_get_max_compressed_size(in_size);
    unsigned char *out = malloc(max_out);
    if (!out) { fprintf(stderr, "out of memory\n"); return 1; }

    /* Compress: FLG_IS_INVERTED=1 (SymbOS uses inverted ZX0) */
    size_t out_size = salvador_compress(in, out, in_size, max_out,
                                        FLG_IS_INVERTED, 32640, 0, NULL, NULL);
    if ((ssize_t)out_size < 0) { fprintf(stderr, "compression error\n"); return 1; }

    fwrite(out, 1, out_size, stdout);

    free(in);
    free(out);
    return 0;
}
