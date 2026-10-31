#include "refresh_policy.h"
#include <string.h>

static bool colored(const uint8_t *p) {
    unsigned lo=p[0],hi=p[0];
    for(unsigned i=1;i<3;i++){if(p[i]<lo)lo=p[i];if(p[i]>hi)hi=p[i];}
    /* Ignore sub-visible RGB rounding, not dark/light gray. A single real
     * colored glyph must still select CFA, regardless of its screen area. */
    return hi-lo>2;
}
static bool image_has_color(const uint8_t *image,size_t stride,unsigned width,unsigned height){
    for(unsigned y=0;y<height;y++)for(unsigned x=0;x<width;x++)
        if(colored(image+(size_t)y*stride+x*4))return true;
    return false;
}
/* Read actual pixels: a black reader theme does not necessarily change the
 * system's brightness setting. Sample the interior to avoid status bars. */
static int background_kind(const uint8_t *image,size_t stride,RefreshRegion r){
    if(!image||!r.width||!r.height)return -1;
    unsigned dark=0,light=0;
    for(unsigned y=0;y<32;y++)for(unsigned x=0;x<32;x++){
        unsigned px=r.left+(unsigned)((uint64_t)(x*2+1)*r.width/64);
        unsigned py=r.top+(unsigned)((uint64_t)(y*2+1)*r.height/64);
        const uint8_t *p=image+(size_t)py*stride+px*4;
        unsigned gray=(77*p[2]+150*p[1]+29*p[0])>>8;
        if(gray<=96)dark++;else if(gray>=160)light++;
    }
    if(dark*100>=1024*65)return 1;
    if(light*100>=1024*65)return 0;
    return -1;
}
uint64_t refresh_deadline(uint64_t pixels_due,uint64_t clean_due,uint64_t next_allowed,uint64_t now){
    if(!clean_due)return pixels_due;
    uint64_t clean_allowed=clean_due>next_allowed?clean_due:next_allowed;
    if(pixels_due==UINT64_MAX)return clean_allowed;
    if(clean_due<=now||clean_due-now<=250000000ULL)
        return pixels_due>clean_allowed?pixels_due:clean_allowed;
    return pixels_due<clean_allowed?pixels_due:clean_allowed;
}
bool refresh_duplicate_clean(uint64_t now,uint64_t last_clean,bool same_pixels){
    return same_pixels&&last_clean&&now>=last_clean&&now-last_clean<=500000000ULL;
}
bool refresh_plan(const uint8_t *old,const uint8_t *next,size_t stride,
                  unsigned width,unsigned height,bool requested_clean,
                  const char *mode,RefreshPlan *out) {
    if(!next||!width||!height||stride<(size_t)width*4)return false;
    unsigned left=width,top=height,right=0,bottom=0,changed=0;
    if(!old) {
        left=top=0;right=width-1;bottom=height-1;changed=width*height;
    } else {
        for(unsigned y=0;y<height;y++) {
            const uint8_t *a=old+y*stride,*b=next+y*stride;
            if(!memcmp(a,b,(size_t)width*4))continue;
            for(unsigned x=0;x<width;x++,a+=4,b+=4) {
                if(a[0]==b[0]&&a[1]==b[1]&&a[2]==b[2])continue;
                if(x<left)left=x;if(x>right)right=x;
                if(y<top)top=y;if(y>bottom)bottom=y;
                changed++;
            }
        }
    }
    bool major=changed>(uint64_t)width*height/100&&left<=right&&top<=bottom&&
        (uint64_t)(right-left+1)*(bottom-top+1)>(uint64_t)width*height/3;
    RefreshRegion interior={width/20,height/10,width-width/10,height-height/5};
    int before=background_kind(old,stride,interior),after=background_kind(next,stride,interior);
    bool night=after>=0?after==1:before==1;
    bool hw_invert=night&&!image_has_color(next,stride,width,height);
    bool polarity_changed=old&&before>=0&&after>=0&&before!=after;
    /* Auto/manual cleanup belongs to the frontend. A second backend page
     * counter can flash immediately before the app's own scheduled cleanup. */
    bool clean=!old||requested_clean||!strcmp(mode,"hd")||polarity_changed;
    if(!changed&&!clean)return false;
    if(clean) {left=top=0;right=width-1;bottom=height-1;}
    else {
        /* MTK may cut a rectangle one pixel short. Add a halo, then align to
         * the 16-pixel constraint used by KOReader, clipping at panel edges. */
        left=(left?left-1:0)/16*16;top=(top?top-1:0)/16*16;
        right=((right+2+15)/16)*16-1;bottom=((bottom+2+15)/16)*16-1;
        if(right>=width)right=width-1;if(bottom>=height)bottom=height-1;
    }
    bool color=false;
    for(unsigned y=top;y<=bottom&&!color;y++) {
        for(unsigned x=left;x<=right;x++) {
            size_t offset=(size_t)y*stride+x*4;
            if(colored(next+offset)||(old&&colored(old+offset))) {color=true;break;}
        }
    }
    /* A white popup over a dark book may need a daytime regional update. */
    if(!clean){int region_kind=background_kind(next,stride,(RefreshRegion){left,top,right-left+1,bottom-top+1});if(region_kind>=0)night=region_kind==1;}
    *out=(RefreshPlan){.region={left,top,right-left+1,bottom-top+1},
        .waveform=color?(clean?REFRESH_GCC16:REFRESH_GLRC16):night?(clean?REFRESH_GCK16:REFRESH_GLKW16):(clean?REFRESH_GC16:REFRESH_GLR16),.flags=color?REFRESH_CFA_G2:0,
        .changed=changed,.clean=clean,.major=major,.color=color,.night=night,.polarity_changed=polarity_changed,.hw_invert=hw_invert};
    return true;
}
