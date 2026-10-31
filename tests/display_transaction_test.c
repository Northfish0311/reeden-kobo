#define _GNU_SOURCE
#include "kobo.h"
#include "refresh_policy.h"
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/ioctl.h>

volatile int app_quit;
bool light_panel_compose(uint8_t *p,size_t s,unsigned w,unsigned h){(void)p;(void)s;(void)w;(void)h;return false;}
static FILE *command_file;
static bool inverted,in_flight,fail_inversion;
static unsigned submitted,completed,last_wave,last_flags,commands;
static uint32_t last_first_pixel;
static Display *display;
static FILE *__real_fopen(const char *path,const char *mode){return fopen(path,mode);}
static int __real_fclose(FILE *f){return fclose(f);}
FILE *__wrap_fopen(const char *path,const char *mode){
    if(!strcmp(path,"/proc/hwtcon/cmd")){assert(!command_file);return command_file=tmpfile();}
    return __real_fopen(path,mode);
}
int __wrap_fclose(FILE *f){
    if(f==command_file){
        char command[64]={0};fflush(f);rewind(f);assert(fread(command,1,sizeof(command)-1,f)>0);
        command_file=NULL;commands++;
        if(!strcmp(command,"night_mode 4")){
            assert(!in_flight);
            if(fail_inversion){__real_fclose(f);errno=EIO;return EOF;}
            inverted=true;
        }else if(!strcmp(command,"night_mode 0")){assert(!in_flight);inverted=false;}
        else assert(!strcmp(command,"fiti_power 1"));
    }
    return __real_fclose(f);
}
struct update_record {uint32_t top,left,width,height,waveform,mode,marker,flags;int dither;};
int __wrap_ioctl(int fd,unsigned long request,...){
    assert(fd==99);va_list args;va_start(args,request);void *p=va_arg(args,void *);va_end(args);
    if(request==0x4024462eUL){
        struct update_record *u=p;assert(!in_flight&&u->mode==1&&u->dither==0);
        assert(u->left%16==0&&u->top%16==0&&u->left+u->width<=64&&u->top+u->height<=64);
        submitted=u->marker;last_wave=u->waveform;last_flags=u->flags;
        last_first_pixel=((uint32_t*)display->mem)[0];in_flight=true;
    }else{
        assert(request==0xc008462fUL);assert(*(uint32_t*)p==submitted&&in_flight);
        completed=submitted;in_flight=false;
    }
    return 0;
}
#define ioctl __wrap_ioctl
#define fopen __wrap_fopen
#define fclose __wrap_fclose
#include "../src/display.c"
#undef ioctl
#undef fopen
#undef fclose
static void flush_now(Display *d){d->last_refresh=d->last_present=d->first_dirty=0;display_flush(d);assert(!in_flight&&completed==submitted);}
int main(void){
    char root[]="/tmp/reeden-display-test-XXXXXX";assert(mkdtemp(root));char path[512];
    snprintf(path,sizeof(path),"%s/state",root);assert(!mkdir(path,0700));assert(!setenv("REEDEN_KOBO_DIR",root,1));
    Display d={.fd=99,.pending_stride=256,.length=16384};display=&d;
    d.v.xres=d.v.yres=64;d.f.line_length=256;
    d.v.red=(struct fb_bitfield){0,8,0};d.v.green=(struct fb_bitfield){8,8,0};
    d.v.blue=(struct fb_bitfield){16,8,0};d.v.transp=(struct fb_bitfield){24,8,0};
    d.pending=malloc(d.length);d.committed=malloc(d.length);d.mem=calloc(1,d.length);assert(d.pending&&d.committed&&d.mem);
    pthread_mutex_init(&d.lock,NULL);strcpy(d.mode,"balanced");
    memset(d.pending,255,d.length);d.frames=1;d.dirty=d.full=true;flush_now(&d);
    assert(last_wave==REFRESH_GC16&&!inverted&&last_first_pixel==0xffffffff);
    memset(d.pending,0,d.length);display_full(&d);flush_now(&d);
    assert(last_wave==REFRESH_GCK16&&inverted&&last_first_pixel==0xffffffff);
    assert(d.committed[0]==0); /* Hardware encoding never poisons logical diff. */
    d.pending[32*256+32*4]=d.pending[32*256+32*4+1]=d.pending[32*256+32*4+2]=255;
    d.dirty=true;flush_now(&d);assert(last_wave==REFRESH_GLKW16&&last_flags==0&&inverted);
    /* A single colored glyph requires CFA and a safe global encoding switch. */
    d.pending[0]=200;d.dirty=true;flush_now(&d);
    assert(last_wave==REFRESH_GCC16&&last_flags==REFRESH_CFA_G2&&!inverted&&last_first_pixel==0xffc80000);
    d.pending[4]=180;d.dirty=true;flush_now(&d);
    assert(last_wave==REFRESH_GLRC16&&last_flags==REFRESH_CFA_G2&&!inverted);
    /* Erasing old color still uses CFA, then gray returns to Eclipse. */
    d.pending[0]=d.pending[4]=0;d.dirty=true;flush_now(&d);
    assert(last_wave==REFRESH_GCC16&&last_flags==REFRESH_CFA_G2&&inverted);
    d.pending[32*256+32*4]=d.pending[32*256+32*4+1]=d.pending[32*256+32*4+2]=0;
    d.dirty=true;flush_now(&d);assert(last_wave==REFRESH_GLKW16&&last_flags==0&&inverted);
    snprintf(path,sizeof(path),"%s/cover.y8",root);FILE *cover=fopen(path,"wb");assert(cover);
    uint8_t white[4096];memset(white,255,sizeof(white));assert(fwrite(white,1,sizeof(white),cover)==sizeof(white));fclose(cover);
    assert(!display_cover(&d,path,64,64));assert(!inverted&&last_wave==REFRESH_GC16);
    unlink(path);snprintf(path,sizeof(path),"%s/state/night-invert",root);assert(access(path,F_OK)<0);
    /* A failed global write must retain its recovery obligation and abort. */
    fail_inversion=true;display_full(&d);flush_now(&d);assert(app_quit&&access(path,F_OK)==0);
    unlink(path);snprintf(path,sizeof(path),"%s/state",root);rmdir(path);rmdir(root);
    free(d.pending);free(d.committed);free(d.mem);pthread_mutex_destroy(&d.lock);
    assert(commands>0);
    puts("PASS: isolated display transactions, RGB packing, grayscale HW inversion, color/erase CFA, completion fences, cover reset and failed-inversion recovery marker; no hardware accessed");
    return 0;
}
