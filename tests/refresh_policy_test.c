#include "refresh_policy.h"
#undef NDEBUG
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { WIDTH=1072, HEIGHT=1448, STRIDE=WIDTH*4 };
static void pixel(uint8_t *p,unsigned x,unsigned y,unsigned b,unsigned g,unsigned r){
    p+=y*STRIDE+x*4;p[0]=b;p[1]=g;p[2]=r;p[3]=255;
}
static void contains(const RefreshPlan *p,unsigned x,unsigned y){
    assert(p->region.left<=x&&p->region.top<=y);
    assert(p->region.left+p->region.width>x&&p->region.top+p->region.height>y);
    assert(p->region.left+p->region.width<=WIDTH&&p->region.top+p->region.height<=HEIGHT);
    assert(p->region.left%16==0&&p->region.top%16==0);
}
int main(void){
    size_t bytes=(size_t)STRIDE*HEIGHT;
    uint8_t *old=malloc(bytes),*next=malloc(bytes);assert(old&&next);
    memset(old,255,bytes);memcpy(next,old,bytes);RefreshPlan p;
    assert(!refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(refresh_plan(NULL,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(p.clean&&p.waveform==2&&!p.color&&p.region.width==WIDTH&&p.region.height==HEIGHT);
    /* A one-pixel change on every edge/boundary must remain covered. */
    unsigned xs[]={0,1,15,16,17,WIDTH-2,WIDTH-1},ys[]={0,1,15,16,17,HEIGHT-2,HEIGHT-1};
    for(unsigned i=0;i<sizeof(xs)/sizeof(*xs);i++)for(unsigned j=0;j<sizeof(ys)/sizeof(*ys);j++){
        memcpy(next,old,bytes);pixel(next,xs[i],ys[j],0,0,0);
        assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
        assert(!p.clean&&!p.major&&!p.color&&p.waveform==4&&p.flags==0&&p.changed==1);
        contains(&p,xs[i],ys[j]);
    }
    /* A stale colored pixel being erased still needs the color pipeline. */
    memset(old,255,bytes);pixel(old,100,100,255,0,0);memset(next,255,bytes);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(p.color&&p.waveform==11&&p.flags==0x600);contains(&p,100,100);
    memset(old,255,bytes);pixel(next,100,100,255,0,0);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,true,"balanced",&p));
    assert(p.color&&p.clean&&p.waveform==10);
    /* Backend must not add a second cleanup cadence over app scheduling. */
    memcpy(next,old,bytes);
    for(unsigned y=30;y<HEIGHT-30;y+=8)for(unsigned x=30;x<WIDTH-30;x+=8)pixel(next,x,y,0,0,0);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(p.major&&!p.clean&&p.waveform==4);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(p.major&&!p.clean&&p.waveform==4);
    /* Explicit clean and HD remain available, even for unchanged pixels. */
    assert(refresh_plan(old,old,STRIDE,WIDTH,HEIGHT,true,"balanced",&p)&&p.clean);
    assert(refresh_plan(old,old,STRIDE,WIDTH,HEIGHT,false,"hd",&p)&&p.clean);
    memcpy(next,old,bytes);next[3]=0;
    assert(!refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(!refresh_plan(old,next,1,WIDTH,HEIGHT,false,"balanced",&p));
    /* Pure black/gray backgrounds need Eclipse, not daytime waveforms. */
    memset(old,0,bytes);memcpy(next,old,bytes);pixel(next,400,400,255,255,255);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(p.night&&!p.color&&!p.clean&&p.waveform==9&&p.flags==0&&p.hw_invert);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,true,"balanced",&p));
    assert(p.night&&p.clean&&p.waveform==8);
    memset(old,40,bytes);memcpy(next,old,bytes);pixel(next,400,400,200,200,200);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p)&&p.night&&p.waveform==9);
    /* Theme polarity changes clean once, using the destination's waveform. */
    memset(old,255,bytes);memset(next,0,bytes);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(p.clean&&p.polarity_changed&&p.night&&p.waveform==8);
    assert(refresh_plan(next,old,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(p.clean&&p.polarity_changed&&!p.night&&p.waveform==2);
    /* A white popup should not use a night regional waveform. */
    memset(old,0,bytes);memcpy(next,old,bytes);
    for(unsigned y=300;y<540;y++)for(unsigned x=200;x<520;x++)pixel(next,x,y,255,255,255);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(!p.clean&&!p.night&&p.waveform==4);
    /* Real color retains Kaleido, including in a dark frame. */
    memset(old,0,bytes);memcpy(next,old,bytes);pixel(next,400,400,200,0,0);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(p.color&&p.waveform==11&&p.flags==0x600);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,true,"balanced",&p)&&p.waveform==10);
    assert(!p.hw_invert);
    /* 16-level grayscale is not binary, and tiny RGB rounding is not color. */
    memset(old,255,bytes);memcpy(next,old,bytes);pixel(next,400,400,126,127,128);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(!p.color&&p.waveform==REFRESH_GLR16);
    pixel(next,400,400,126,127,129);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p)&&p.color);
    /* Color outside a gray dirty region still prevents global HW inversion. */
    memset(old,0,bytes);pixel(old,10,10,200,0,0);memcpy(next,old,bytes);pixel(next,400,400,255,255,255);
    assert(refresh_plan(old,next,STRIDE,WIDTH,HEIGHT,false,"balanced",&p));
    assert(!p.color&&!p.hw_invert&&p.night);
    /* Merge nearby cleanup with pixels, while honoring long delays. */
    const uint64_t ms=1000000ULL;
    assert(refresh_deadline(40*ms,80*ms,0,0)==80*ms);
    assert(refresh_deadline(120*ms,80*ms,0,0)==120*ms);
    assert(refresh_deadline(40*ms,1000*ms,0,0)==40*ms);
    assert(refresh_deadline(UINT64_MAX,80*ms,140*ms,0)==140*ms);
    assert(refresh_deadline(UINT64_MAX,0,0,0)==UINT64_MAX);
    assert(refresh_deadline(40*ms,0,0,0)==40*ms);
    assert(refresh_duplicate_clean(500*ms,100*ms,true));
    assert(!refresh_duplicate_clean(700*ms,100*ms,true));
    assert(!refresh_duplicate_clean(500*ms,100*ms,false));
    assert(!refresh_duplicate_clean(500*ms,0,true));
    free(old);free(next);
    puts("PASS: day/night/gray/color, polarity changes and white popups, 49 edge regions, frontend cleanup ownership and timing coalescence");
    return 0;
}
