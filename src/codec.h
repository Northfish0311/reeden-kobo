#pragma once
#include <stddef.h>
#include <stdint.h>
typedef struct { const uint8_t *p; size_t n, pos; int error; } Reader;
typedef struct { uint8_t data[16384]; size_t n; int error; } Writer;
typedef struct { int type; int64_t integer; double real; char string[4096]; } Value;
int read_value(Reader *, Value *);
int read_method(Reader *, char *, size_t);
int read_argument(Reader, const char *, Value *);
void w_byte(Writer *, unsigned);
void w_null(Writer *);
void w_bool(Writer *, int);
void w_int(Writer *, int64_t);
void w_string(Writer *, const char *);
void w_list(Writer *, unsigned);
void w_map(Writer *, unsigned);
