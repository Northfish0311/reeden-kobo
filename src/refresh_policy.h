#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct { unsigned left,top,width,height; } RefreshRegion;
typedef struct {
    RefreshRegion region;
    uint32_t waveform,flags;
    unsigned changed;
    bool clean,major,color,night,polarity_changed,hw_invert;
} RefreshPlan;

enum { REFRESH_GC16=2, REFRESH_GLR16=4, REFRESH_GCK16=8,
       REFRESH_GLKW16=9, REFRESH_GCC16=10, REFRESH_GLRC16=11,
       REFRESH_CFA_G2=0x600 };

/* The old image is a RAM copy of the last successfully submitted BGRA frame.
 * A NULL old image forces initialization. Alpha changes alone are invisible. */
bool refresh_plan(const uint8_t *old,const uint8_t *next,size_t stride,
                  unsigned width,unsigned height,bool requested_clean,
                  const char *mode,RefreshPlan *out);
/* Reeden owns auto/manual cleanup cadence. The backend only coalesces a
 * nearby cleanup with pixels waiting to be submitted. Zero means no request. */
uint64_t refresh_deadline(uint64_t pixels_due,uint64_t clean_due,
                          uint64_t next_allowed,uint64_t now);
bool refresh_duplicate_clean(uint64_t now,uint64_t last_clean,bool same_pixels);
