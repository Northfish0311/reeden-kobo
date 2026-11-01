#include "kobo.h"
#include "refresh_policy.h"
#include "light_panel.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <time.h>
/* Kernel HWTCON UAPI layout; verified against KOReader's mxcfb_kobo_h.lua. */
struct rect { uint32_t top,left,width,height; };
struct update { struct rect region; uint32_t waveform,mode,marker,flags; int dither; };
#define SEND_UPDATE 0x4024462eUL
#define WAIT_COMPLETE 0xc008462fUL
_Static_assert(sizeof(struct update)==36,"HWTCON update ABI");
uint64_t monotonic_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
int read_number(const char *p,int fallback){FILE *f=fopen(p,"r");int n=fallback;if(f){if(fscanf(f,"%d",&n)!=1)n=fallback;fclose(f);}return n;}
int write_number(const char *p,int n){FILE *f=fopen(p,"w");if(!f)return -1;int a=fprintf(f,"%d\n",n);int b=fclose(f);return a>0&&b==0?0:-1;}
static int display_command(const char *command){
    FILE *f=fopen("/proc/hwtcon/cmd","w");if(!f)return -1;
    int a=fputs(command,f),b=fclose(f);return a>=0&&b==0?0:-1;
}
static int display_inversion(Display *d,bool inverted){
    char path[4096];const char *root=getenv("REEDEN_KOBO_DIR");
    if(root){
        snprintf(path,sizeof(path),"%s/state/night-invert",root);
        /* Persist the reset obligation before touching the global knob. */
        if(inverted){FILE *f=fopen(path,"w");if(!f)return -1;if(fclose(f))return -1;}
    }
    if(display_command(inverted?"night_mode 4":"night_mode 0"))return -1;
    if(root&&!inverted)unlink(path);
    d->hw_inverted=inverted;d->hw_state_known=true;
    fprintf(stderr,"[display] hardware inversion=%u\n",inverted);
    return 0;
}
int display_open(Display *d){
    memset(d,0,sizeof(*d));d->fd=-1;pthread_mutex_init(&d->lock,NULL);strcpy(d->mode,"balanced");
    const char *p=getenv("REEDEN_FB");if(!p)p="/dev/fb0";
    d->fd=open(p,O_RDONLY|O_CLOEXEC);if(d->fd<0)return -1;
    if(ioctl(d->fd,FBIOGET_VSCREENINFO,&d->v)||ioctl(d->fd,FBIOGET_FSCREENINFO,&d->f))return -1;
    if(strncmp(d->f.id,"hwtcon",6)||d->v.bits_per_pixel!=32||d->v.xres>4096||d->v.yres>4096||!d->v.xres||!d->v.yres){errno=ENOTSUP;return -1;}
    struct fb_bitfield fields[]={d->v.red,d->v.green,d->v.blue,d->v.transp};
    for(unsigned i=0;i<4;i++)if(fields[i].length>8||fields[i].offset+fields[i].length>32||fields[i].msb_right){errno=ENOTSUP;return -1;}
    d->length=d->f.smem_len;
    if((uint64_t)(d->v.yoffset+d->v.yres)*d->f.line_length>d->length || (d->v.xoffset+d->v.xres)*4>d->f.line_length){errno=EINVAL;return -1;}
    close(d->fd);d->fd=-1;
    d->pending_stride=d->v.xres*4;d->pending=malloc(d->pending_stride*d->v.yres);
    d->committed=malloc(d->pending_stride*d->v.yres);if(!d->pending||!d->committed)return -1;
    fprintf(stderr,"[display] %s %ux%u bpp=%u stride=%u rotation=%u RGB offsets=%u/%u/%u\n",d->f.id,d->v.xres,d->v.yres,d->v.bits_per_pixel,d->f.line_length,d->v.rotate,d->v.red.offset,d->v.green.offset,d->v.blue.offset);
    return 0;
}
int display_acquire(Display *d){
    const char *p=getenv("REEDEN_FB");if(!p)p="/dev/fb0";
    d->fd=open(p,O_RDWR|O_CLOEXEC);if(d->fd<0)return -1;
    struct fb_var_screeninfo v;struct fb_fix_screeninfo f;
    if(ioctl(d->fd,FBIOGET_VSCREENINFO,&v)||ioctl(d->fd,FBIOGET_FSCREENINFO,&f))return -1;
    if(v.xres!=d->v.xres||v.yres!=d->v.yres||v.bits_per_pixel!=32||v.rotate!=d->v.rotate||v.xoffset!=d->v.xoffset||v.yoffset!=d->v.yoffset||f.smem_len!=d->f.smem_len||f.line_length!=d->f.line_length||memcmp(&v.red,&d->v.red,sizeof(v.red))||memcmp(&v.green,&d->v.green,sizeof(v.green))||memcmp(&v.blue,&d->v.blue,sizeof(v.blue))){errno=ESTALE;return -1;}
    d->mem=mmap(NULL,d->length,PROT_READ|PROT_WRITE,MAP_SHARED,d->fd,0);if(d->mem==MAP_FAILED){d->mem=NULL;return -1;}
    return display_inversion(d,false);
}
bool display_present(Display *d,const void *pixels,size_t row,size_t height){
    if(!pixels||height!=d->v.yres||row<d->pending_stride){fprintf(stderr,"[display] rejected surface: row=%zu height=%zu\n",row,height);return false;}
    pthread_mutex_lock(&d->lock);
    bool changed=!d->frames;
    for(unsigned y=0;y<height;y++){
        const uint8_t *src=(const uint8_t*)pixels+y*row;
        uint8_t *dst=d->pending+y*d->pending_stride;
        if(!d->frames||memcmp(dst,src,d->pending_stride)){memcpy(dst,src,d->pending_stride);changed=true;}
    }
    if(d->use_light_overlay&&light_panel_compose(d->pending,d->pending_stride,d->v.xres,d->v.yres))changed=true;
    if(changed){uint64_t now=monotonic_ns();if(!d->dirty)d->first_dirty=now;d->dirty=true;d->last_present=now;}
    d->frames++;
    if(d->frames==1){d->full=true;fprintf(stderr,"[display] FIRST_FRAME_RECEIVED\n");}
    pthread_mutex_unlock(&d->lock);return true;
}
static uint32_t field(unsigned c,struct fb_bitfield f){return f.length?((c>>(8-f.length))<<f.offset):0;}
void display_full(Display *d){pthread_mutex_lock(&d->lock);if(!d->dirty)d->first_dirty=monotonic_ns();d->full=true;d->dirty=true;pthread_mutex_unlock(&d->lock);}
void display_request_full(Display *d,unsigned delay_ms){
    uint64_t due=monotonic_ns()+(uint64_t)delay_ms*1000000ULL;
    pthread_mutex_lock(&d->lock);
    if(!d->request_clean_at||due<d->request_clean_at)d->request_clean_at=due;
    pthread_mutex_unlock(&d->lock);
}
static uint64_t deadline_locked(Display *d){
    if(!d->frames)return UINT64_MAX;
    uint64_t interval=!strcmp(d->mode,"fast")?80000000ULL:140000000ULL;
    uint64_t settled=d->last_present+40000000ULL,limit=d->first_dirty+400000000ULL;
    if(settled>limit)settled=limit;
    uint64_t allowed=d->last_refresh+interval;
    uint64_t pixels_due=d->dirty?(allowed>settled?allowed:settled):UINT64_MAX;
    return refresh_deadline(pixels_due,d->request_clean_at,allowed,monotonic_ns());
}
uint64_t display_deadline(Display *d){pthread_mutex_lock(&d->lock);uint64_t t=deadline_locked(d);pthread_mutex_unlock(&d->lock);return t;}
static void flush(Display *d,const uint8_t *cover){
    uint64_t now=monotonic_ns();pthread_mutex_lock(&d->lock);
    if(!cover&&now<deadline_locked(d)){pthread_mutex_unlock(&d->lock);return;}
    if(!cover&&d->request_clean_at&&now>=d->request_clean_at){
        d->request_clean_at=0;
        bool same=d->committed_valid&&!memcmp(d->pending,d->committed,d->pending_stride*d->v.yres);
        if(!d->full&&refresh_duplicate_clean(now,d->last_clean,same)){
            fprintf(stderr,"[refresh] coalesced duplicate cleanup for unchanged pixels\n");
        }else{
            if(!d->dirty)d->first_dirty=now;
            d->full=true;d->dirty=true;
        }
    }
    if(!cover&&!d->dirty){pthread_mutex_unlock(&d->lock);return;}
    const uint8_t *source=cover?cover:d->pending;
    RefreshPlan plan;
    if(!refresh_plan(d->committed_valid?d->committed:NULL,source,d->pending_stride,
                     d->v.xres,d->v.yres,cover||d->full,d->mode,&plan)){
        d->dirty=false;pthread_mutex_unlock(&d->lock);return;
    }
    if(cover)plan.hw_invert=false;
    bool inversion_change=!d->hw_state_known||d->hw_inverted!=plan.hw_invert;
    if(inversion_change){
        /* Every pixel's physical encoding changes with this GLOBAL flag. */
        refresh_plan(d->committed_valid?d->committed:NULL,source,d->pending_stride,
                     d->v.xres,d->v.yres,true,d->mode,&plan);
        if(cover)plan.hw_invert=false;
    }
    /* Wake before either wait or submit, as in KOReader's MTK path. */
    if(display_command("fiti_power 1")){perror("display wake");app_quit=1;pthread_mutex_unlock(&d->lock);return;}
    if(display_wait(d)<0){fprintf(stderr,"[display] wait for prior update failed: %s\n",strerror(errno));app_quit=1;pthread_mutex_unlock(&d->lock);return;}
    if(inversion_change&&display_inversion(d,plan.hw_invert)){perror("display inversion");app_quit=1;pthread_mutex_unlock(&d->lock);return;}
    unsigned endx=plan.region.left+plan.region.width,endy=plan.region.top+plan.region.height;
    uint32_t alpha=field(255,d->v.transp);
    bool native_rgb=d->v.red.length==8&&d->v.green.length==8&&d->v.blue.length==8&&
        d->v.red.offset==0&&d->v.green.offset==8&&d->v.blue.offset==16;
    for(unsigned y=plan.region.top;y<endy;y++){
        uint32_t *dst=(uint32_t*)(d->mem+(y+d->v.yoffset)*d->f.line_length+d->v.xoffset*4);
        const uint8_t *src=source+y*d->pending_stride;
        for(unsigned x=plan.region.left;x<endx;x++){
            const uint8_t *p=src+x*4;
            unsigned b=p[0],g=p[1],r=p[2];
            /* Dart already rendered the dark theme. Give the driver's
             * inversion the complementary grayscale input, keeping the
             * logical committed image unchanged. Real-color frames remain
             * in the direct CFA path: post-CFA inversion is not RGB inverse. */
            if(plan.hw_invert){b=255-b;g=255-g;r=255-r;}
            dst[x]=native_rgb?((uint32_t)b<<16)|((uint32_t)g<<8)|r|alpha:
                field(r,d->v.red)|field(g,d->v.green)|field(b,d->v.blue)|alpha;
        }
    }
    {
        /* REAGL and Kaleido both require UPDATE_MODE_FULL on this model;
         * that flag does not itself mean a full-screen flashing cleanup. */
        struct update u={.region={plan.region.top,plan.region.left,plan.region.width,plan.region.height},.waveform=plan.waveform,.mode=1,.marker=++d->marker,.flags=plan.flags};
        if(ioctl(d->fd,SEND_UPDATE,&u)<0){fprintf(stderr,"[display] HWTCON_SEND_UPDATE failed: %s\n",strerror(errno));d->full=true;d->failures++;if(d->failures>=3)app_quit=1;}
        else {
            for(unsigned y=plan.region.top;y<endy;y++)memcpy(
                d->committed+y*d->pending_stride+plan.region.left*4,
                source+y*d->pending_stride+plan.region.left*4,plan.region.width*4);
            d->committed_valid=true;
            d->full=false;d->failures=0;d->refreshes++;
            if(plan.clean){d->last_clean=monotonic_ns();d->clean_refreshes++;}
            if(plan.night&&!plan.color)d->night_refreshes++;
            if(plan.color)d->color_refreshes++;else d->gray_refreshes++;
            if(cover)d->request_clean_at=0;
            /* FULL REAGL/CFA transactions are completed before another
             * framebuffer or global inversion change, matching KOReader. */
            if(display_wait(d)<0){fprintf(stderr,"[display] wait for completion failed: %s\n",strerror(errno));app_quit=1;}
            if(d->refreshes==1)fprintf(stderr,"[display] FIRST_UPDATE_SUBMITTED marker=%u\n",u.marker);
            if(d->refreshes<=30||plan.clean||d->last_waveform!=u.waveform)fprintf(stderr,"[refresh] marker=%u wave=%u clean=%u color=%u night=%u hw_invert=%u flags=0x%x dither=%d transition=%u region=%u,%u %ux%u changed=%u work_ms=%.1f\n",
                u.marker,u.waveform,plan.clean,plan.color,plan.night,plan.hw_invert,u.flags,u.dither,plan.polarity_changed,plan.region.left,plan.region.top,plan.region.width,plan.region.height,plan.changed,(monotonic_ns()-now)/1000000.0);
            d->last_waveform=u.waveform;
        }
        d->last_refresh=monotonic_ns();
    }
    d->dirty=d->failures>0;pthread_mutex_unlock(&d->lock);
}
void display_flush(Display *d){flush(d,NULL);}
int display_wait(Display *d){
    if(!d->refreshes||d->completed_marker==d->marker)return 0;
    uint32_t marker[2]={d->marker,0};int result=ioctl(d->fd,WAIT_COMPLETE,marker);
    if(result>=0)d->completed_marker=d->marker;
    return result;
}
int display_cover(Display *d,const char *path,unsigned width,unsigned height,unsigned channels){
    if(!width||!height||width>4096||height>4096||channels<1||channels>4){errno=EINVAL;return -1;}
    FILE *f=fopen(path,"rb");if(!f)return -1;
    size_t total=(size_t)width*height*channels;
    uint8_t *raw=malloc(total),*bgra=malloc(d->pending_stride*d->v.yres);
    if(!raw||!bgra){free(raw);free(bgra);fclose(f);errno=ENOMEM;return -1;}
    bool valid=fread(raw,1,total,f)==total&&fgetc(f)==EOF;fclose(f);
    if(!valid){free(raw);free(bgra);errno=EINVAL;return -1;}
    if((channels==2||channels==4)&&d->committed_valid&&d->committed)
        memcpy(bgra,d->committed,d->pending_stride*d->v.yres);
    else memset(bgra,255,d->pending_stride*d->v.yres);
    int ox=((int)d->v.xres-(int)width)/2,oy=((int)d->v.yres-(int)height)/2;
    for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++){
        int dx=(int)x+ox,dy=(int)y+oy;if(dx<0||dy<0||dx>=(int)d->v.xres||dy>=(int)d->v.yres)continue;
        const uint8_t *px=raw+((size_t)y*width+x)*channels;
        uint8_t sr=px[0],sg=channels>=3?px[1]:px[0],sb=channels>=3?px[2]:px[0];
        uint8_t sa=channels==2?px[1]:(channels==4?px[3]:255);
        uint8_t *p=bgra+dy*d->pending_stride+dx*4;
        if(sa==255){p[0]=sb;p[1]=sg;p[2]=sr;p[3]=255;}
        else if(sa>0){
            unsigned inv=255u-sa;
            unsigned b=sb+((unsigned)p[0]*inv*0x8081u>>23);
            unsigned g=sg+((unsigned)p[1]*inv*0x8081u>>23);
            unsigned r=sr+((unsigned)p[2]*inv*0x8081u>>23);
            p[0]=b>255?255:(uint8_t)b;
            p[1]=g>255?255:(uint8_t)g;
            p[2]=r>255?255:(uint8_t)r;
            p[3]=255;
        }
    }
    flush(d,bgra);int result=display_wait(d);free(raw);free(bgra);return result;
}
void display_close(Display *d){if(d->mem&&d->hw_state_known){display_wait(d);if(display_inversion(d,false))perror("reset display inversion");}if(d->mem)munmap(d->mem,d->length);if(d->fd>=0)close(d->fd);free(d->pending);free(d->committed);pthread_mutex_destroy(&d->lock);}
