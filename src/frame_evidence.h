#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <linux/fb.h>
#include "refresh_policy.h"

/* Opt-in local diagnostic capture. No capture directory is created by default.
 * This is intentionally synchronous and unsuitable for latency benchmarks. */
typedef struct {
    char directory[1024];
    unsigned limit,used;
    bool quality_after_turn,reagl_bands;
    unsigned quality_every;
} FrameEvidenceOptions;
typedef struct {
    unsigned width,height,logical_stride,rotation;
    unsigned fb_stride,xoffset,yoffset;
    struct fb_bitfield red,green,blue,alpha;
    RefreshPlan plan;
    bool old_valid,animated;
    const char *profile;
    const char *band_path;
    uint64_t trace_id;
} FrameEvidenceInfo;
typedef struct { int fd; bool active,ok; uint64_t begin_ns; } FrameCapture;
bool frame_evidence_options_load(FrameEvidenceOptions *);
FrameCapture frame_capture_begin(FrameEvidenceOptions *,const FrameEvidenceInfo *,
                                const uint8_t *old,const uint8_t *target,
                                const uint8_t *fb,size_t fb_bytes);
void frame_capture_pixels(FrameCapture *,const char *name,const uint8_t *,size_t);
void frame_capture_end(FrameCapture *,const char *outcome,uint32_t last_marker,
                       unsigned quality_status);
