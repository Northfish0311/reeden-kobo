#ifndef REEDEN_NATIVE_TEST_FB_H
#define REEDEN_NATIVE_TEST_FB_H
/* Test-only field model for the ioctl mock on macOS. Never include this path
 * in ARM builds. This is NOT an assertion about the target kernel's ABI. */
#include <stdint.h>
struct fb_bitfield {uint32_t offset,length,msb_right;};
struct fb_var_screeninfo {
    uint32_t xres,yres,xres_virtual,yres_virtual,xoffset,yoffset,bits_per_pixel;
    struct fb_bitfield red,green,blue,transp;
    uint32_t rotate;
};
struct fb_fix_screeninfo {char id[16];uint32_t smem_len,line_length;};
#define FBIOGET_VSCREENINFO 0x4600
#define FBIOGET_FSCREENINFO 0x4602
#endif
