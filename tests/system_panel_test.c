#include "system_panel.h"
#undef NDEBUG
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
enum { W=1072,H=1448,ROW=W*4 };
static enum panel_action action;
static unsigned invalidations,forwards;
static FlutterPointerPhase forwarded[32];
static void invalidate(void *u){(void)u;invalidations++;}
static void request(enum panel_action a){action=a;}
static void forward(const FlutterPointerEvent *p){assert(forwards<32);forwarded[forwards++]=p->phase;}
static bool point(int id,FlutterPointerPhase phase,double x,double y){
    FlutterPointerEvent p={.struct_size=sizeof(p),.device=id,.phase=phase,.x=x,.y=y};
    return system_panel_pointer(&p);
}
static void swipe(void){
    assert(point(1,kAdd,536,4));assert(point(1,kDown,536,4));
    assert(point(1,kMove,536,140));assert(point(1,kUp,536,140));assert(point(1,kRemove,536,140));
    assert(system_panel_visible()&&action==PANEL_PROBE);
}
static void tap(double x,double y){
    assert(point(2,kAdd,x,y));assert(point(2,kDown,x,y));assert(point(2,kUp,x,y));assert(point(2,kRemove,x,y));
}
static void screenshot(const char *path,const uint8_t *pixels){
    FILE *f=fopen(path,"wb");assert(f);fprintf(f,"P6\n%d %d\n255\n",W,H);
    for(unsigned i=0;i<W*H;i++)assert(fwrite(pixels+i*4,1,3,f)==3);
    assert(!fclose(f));
}
int main(int argc,char **argv){
    SystemPanelOps ops={.invalidate=invalidate,.request=request,.forward=forward};
    system_panel_init(ops);
    assert(!point(9,kAdd,536,4));assert(!point(9,kRemove,536,4));
    system_panel_available(true,1);
    assert(point(1,kAdd,536,4));assert(point(1,kDown,536,4));
    assert(!point(1,kUp,536,4));assert(!point(1,kRemove,536,4));
    assert(forwards==2&&forwarded[0]==kAdd&&forwarded[1]==kDown&&!system_panel_visible());
    assert(point(1,kAdd,536,4));assert(point(1,kDown,536,4));
    assert(!point(2,kAdd,700,600));assert(!point(1,kMove,536,140));
    assert(!point(1,kCancel,536,140));assert(!point(2,kRemove,700,600));
    assert(!system_panel_visible()&&forwards==4);
    swipe();assert(forwards==4);
    uint8_t *image=malloc((size_t)ROW*H),*original=malloc((size_t)ROW*H);assert(image&&original);
    memset(original,255,(size_t)ROW*H);
    for(unsigned y=120;y<1300;y+=60)for(unsigned x=80;x<990;x++)for(unsigned j=0;j<3;j++)original[y*ROW+x*4+j]=65;
    memcpy(image,original,(size_t)ROW*H);
    system_panel_network(PANEL_CONNECTED,false,false);
    assert(system_panel_compose(image,ROW,W,H));
    assert(image[400*ROW+200*4]==255&&image[100*ROW]==223);
    assert(image[540*ROW+800*4]==25&&image[540*ROW+870*4]==255);
    if(argc>1)screenshot(argv[1],image);
    action=PANEL_NONE;tap(840,550);assert(action==PANEL_WIFI_OFF);
    action=PANEL_NONE;tap(840,550);assert(action==PANEL_NONE); /* Busy: no duplicate write. */
    system_panel_network(PANEL_OFF,false,false);tap(840,550);assert(action==PANEL_WIFI_ON);
    system_panel_network(PANEL_UNKNOWN,false,true);action=PANEL_NONE;tap(840,550);assert(action==PANEL_NONE);
    tap(790,425);assert(action==PANEL_PROBE);
    tap(700,900);assert(!system_panel_visible());
    assert(system_panel_redraw(image,ROW,W,H));assert(!memcmp(image,original,(size_t)ROW*H));
    swipe();system_panel_network(PANEL_ON,false,false);
    memset(original,180,(size_t)ROW*H);memcpy(image,original,(size_t)ROW*H);
    assert(system_panel_compose(image,ROW,W,H));
    system_panel_hide();assert(system_panel_redraw(image,ROW,W,H));
    assert(!memcmp(image,original,(size_t)ROW*H)); /* Most recent Flutter frame, not stale pixels. */
    swipe();tap(300,900);assert(action==PANEL_LOCK&&!system_panel_visible());
    assert(!system_panel_compose(image,ROW,800,600));
    assert(invalidations>5);
    free(image);free(original);system_panel_destroy();
    puts("PASS: panel gesture, tap replay, multitouch cancellation, radio states, busy guard, lock and exact frame restore");
    return 0;
}
