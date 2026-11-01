#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <pthread.h>
#include <linux/fb.h>
#include "embedder.h"
typedef struct {
    int fd; uint8_t *mem; size_t length; struct fb_var_screeninfo v; struct fb_fix_screeninfo f;
    pthread_mutex_t lock; uint8_t *pending,*committed; size_t pending_stride; bool dirty,full,committed_valid;
    unsigned frames,marker,refreshes,failures; uint64_t last_refresh; char mode[32];
    uint64_t last_present,first_dirty,request_clean_at,last_clean;
    unsigned clean_refreshes,gray_refreshes,color_refreshes,night_refreshes,last_waveform;
    unsigned completed_marker; bool hw_inverted,hw_state_known,use_light_overlay;
} Display;
typedef struct { int id,x,y; bool active,seen,down; double last_x,last_y; } Contact;
typedef struct {
    int fd,slot,id; bool slots,dropped; int max_x,max_y,min_x,min_y;
    Contact contacts[16], report[16], current; unsigned report_count;
} Touch;
int display_open(Display *);
int display_acquire(Display *);
bool display_present(Display *,const void *,size_t,size_t);
void display_flush(Display *);
void display_full(Display *);
void display_request_full(Display *,unsigned);
uint64_t display_deadline(Display *);
int display_cover(Display *,const char *,unsigned,unsigned,unsigned);
int display_wait(Display *);
void display_close(Display *);
int touch_open(Touch *);
void touch_process(Touch *,FlutterEngine,unsigned,unsigned);
void touch_close(Touch *,FlutterEngine);
void touch_set_filter(bool (*)(FlutterPointerEvent *));
uint64_t monotonic_ns(void);
int read_number(const char *,int);
int write_number(const char *,int);
extern volatile int app_quit;
