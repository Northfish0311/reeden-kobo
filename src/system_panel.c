#include "system_panel.h"
#include "system_panel_art.h"
#ifdef _WIN32
#include <windows.h>
static SRWLOCK mutex=SRWLOCK_INIT;
static void lock_panel(void){AcquireSRWLockExclusive(&mutex);}
static void unlock_panel(void){ReleaseSRWLockExclusive(&mutex);}
#else
#include <pthread.h>
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static void lock_panel(void){pthread_mutex_lock(&mutex);}
static void unlock_panel(void){pthread_mutex_unlock(&mutex);}
#endif
#include <stdlib.h>
#include <string.h>
#include <math.h>

enum { W=1072,H=1448,STRIDE=W*4,MODAL_LEFT=116,MODAL_TOP=360,MODAL_RIGHT=956,MODAL_BOTTOM=1000 };
enum contact_mode { PASS=1, EDGE, CAPTURE, MODAL };
typedef struct { int64_t id; int mode; bool added,down; FlutterPointerEvent add,start; } PanelContact;
static SystemPanelOps ops;
static PanelContact contacts[16];
static bool available,shown,painted,busy,failed;
static int cover_status;
static enum panel_wifi network;
static uint8_t *base;

static void invalidate(void){if(ops.invalidate)ops.invalidate(ops.userdata);}
void system_panel_init(SystemPanelOps callbacks){
    lock_panel();
    ops=callbacks;available=shown=painted=busy=failed=false;network=PANEL_UNKNOWN;cover_status=-1;
    memset(contacts,0,sizeof(contacts));free(base);base=NULL;
    unlock_panel();
}
void system_panel_available(bool yes,int cover){lock_panel();available=yes;cover_status=cover;unlock_panel();}
bool system_panel_visible(void){lock_panel();bool yes=shown;unlock_panel();return yes;}
void system_panel_network(enum panel_wifi state,bool working,bool error){
    lock_panel();network=state;busy=working;failed=error;unlock_panel();invalidate();
}
void system_panel_hide(void){lock_panel();shown=false;unlock_panel();invalidate();}
void system_panel_destroy(void){lock_panel();free(base);base=NULL;shown=available=painted=false;unlock_panel();}

static void rectangle(uint8_t *p,size_t stride,int x,int y,int w,int h,int gray){
    for(int row=y;row<y+h;row++)for(int col=x;col<x+w;col++){
        uint8_t *v=p+row*stride+col*4;v[0]=v[1]=v[2]=gray;v[3]=255;
    }
}
static void label(uint8_t *p,size_t stride,int x,int y,PanelLabel text,int gray){
    for(unsigned row=0;row<text.height;row++)for(unsigned col=0;col<text.width;col++){
        unsigned bit=row*text.width+col;if(!(text.bits[bit/8]&(128>>(bit%8))))continue;
        uint8_t *v=p+(y+row)*stride+(x+col)*4;v[0]=v[1]=v[2]=gray;v[3]=255;
    }
}
static void button(uint8_t *p,size_t stride,int x,int y,int w,int h,PanelLabel text,bool primary){
    rectangle(p,stride,x,y,w,h,primary?20:160);
    if(!primary)rectangle(p,stride,x+2,y+2,w-4,h-4,255);
    label(p,stride,x+(w-(int)text.width)/2,y+(h-(int)text.height)/2,text,primary?255:20);
}
static void draw(uint8_t *p,size_t stride){
    for(unsigned y=0;y<H;y++)for(unsigned x=0;x<W;x++){
        uint8_t *v=p+y*stride+x*4;unsigned gray=(v[0]+v[1]+v[2])/3;
        v[0]=v[1]=v[2]=160+gray/4;
    }
    rectangle(p,stride,MODAL_LEFT,MODAL_TOP,840,640,40);
    rectangle(p,stride,MODAL_LEFT+2,MODAL_TOP+2,836,636,255);
    label(p,stride,156,404,panel_title,20);
    button(p,stride,730,394,120,62,panel_refresh,false);
    for(int i=0;i<24;i++){rectangle(p,stride,881+i,410+i,3,3,30);rectangle(p,stride,904-i,410+i,3,3,30);}
    rectangle(p,stride,156,474,760,2,210);
    label(p,stride,156,518,panel_wifi,20);
    PanelLabel status=network==PANEL_OFF?panel_off:network==PANEL_ON?panel_on:network==PANEL_CONNECTED?panel_connected:panel_unknown;
    label(p,stride,156,575,busy?panel_busy:failed?panel_error:status,75);
    int shade=busy?180:network>=PANEL_ON?25:150;
    rectangle(p,stride,776,523,140,64,shade);
    rectangle(p,stride,network>=PANEL_ON?852:784,531,56,48,255);
    rectangle(p,stride,156,643,760,2,220);
    label(p,stride,156,685,panel_cover,20);
    label(p,stride,156,741,cover_status>0?panel_enabled:cover_status==0?panel_disabled:panel_unsupported,75);
    rectangle(p,stride,156,819,760,2,220);
    button(p,stride,156,871,358,76,panel_lock,false);
    button(p,stride,538,871,378,76,panel_back,true);
}
static bool surface(uint8_t *p,size_t stride,unsigned width,unsigned height){return p&&width==W&&height==H&&stride>=STRIDE;}
static void copy_base(uint8_t *p,size_t stride,bool save){
    for(unsigned y=0;y<H;y++)if(save)memcpy(base+y*STRIDE,p+y*stride,STRIDE);else memcpy(p+y*stride,base+y*STRIDE,STRIDE);
}
bool system_panel_compose(uint8_t *p,size_t stride,unsigned width,unsigned height){
    lock_panel();bool result=false;
    if(surface(p,stride,width,height)){
        painted=false;
        if(available&&shown){
            if(!base)base=malloc((size_t)STRIDE*H);
            if(base){copy_base(p,stride,true);draw(p,stride);painted=true;result=true;}else shown=false;
        }
    }
    unlock_panel();return result;
}
bool system_panel_redraw(uint8_t *p,size_t stride,unsigned width,unsigned height){
    lock_panel();bool result=false;
    if(surface(p,stride,width,height)){
        if(shown&&available){
            if(!base)base=malloc((size_t)STRIDE*H);
            if(base){copy_base(p,stride,!painted);draw(p,stride);painted=true;result=true;}else shown=false;
        }else if(painted&&base){copy_base(p,stride,false);painted=false;result=true;}
    }
    unlock_panel();return result;
}
static bool inside(double x,double y,int left,int top,int right,int bottom){return x>=left&&x<right&&y>=top&&y<bottom;}
bool system_panel_pointer(FlutterPointerEvent *p){
    FlutterPointerEvent replay[2];unsigned replay_count=0;
    enum panel_action action=PANEL_NONE;bool redraw=false,consumed=false;
    lock_panel();
    PanelContact *c=NULL;
    for(unsigned i=0;i<16;i++)if(contacts[i].mode&&contacts[i].id==p->device)c=&contacts[i];
    if(!c&&(p->phase==kAdd||p->phase==kDown)){
        bool others=false;for(unsigned i=0;i<16;i++)if(contacts[i].mode)others=true;
        for(unsigned i=0;i<16;i++)if(!contacts[i].mode){
            c=&contacts[i];*c=(PanelContact){.id=p->device,.mode=PASS};
            if(available&&shown)c->mode=MODAL;
            else if(available&&!others&&inside(p->x,p->y,300,0,772,24))c->mode=EDGE;
            break;
        }
        /* A second finger cancels a pending one-finger edge gesture. */
        if(others)for(unsigned i=0;i<16;i++)if(contacts[i].mode==EDGE){
            PanelContact *edge=&contacts[i];
            if(edge->added)replay[replay_count++]=edge->add;
            if(edge->down)replay[replay_count++]=edge->start;
            edge->mode=PASS;break;
        }
    }
    if(c){
        if(p->phase==kAdd){c->add=*p;c->added=true;}
        if(p->phase==kDown){c->start=*p;c->down=true;}
        if(c->mode==EDGE){
            double dx=fabs(p->x-c->start.x),dy=p->y-c->start.y;
            if(p->phase==kMove&&c->down&&dy>=100&&dy>dx+40){
                c->mode=CAPTURE;shown=true;busy=true;failed=false;redraw=true;action=PANEL_PROBE;
            }else if(p->phase==kUp||p->phase==kCancel||p->phase==kRemove||(p->phase==kMove&&(dx>60||dy< -20))){
                if(c->added)replay[replay_count++]=c->add;
                if(c->down)replay[replay_count++]=c->start;
                c->mode=PASS;
            }
        }
        if(c->mode==MODAL&&p->phase==kUp&&c->down&&shown){
            double x=p->x,y=p->y;
            bool tap=fabs(x-c->start.x)<40&&fabs(y-c->start.y)<40;
            if(tap){
                if(inside(x,y,864,390,928,454)||inside(x,y,538,871,916,947))shown=false;
                else if(inside(x,y,156,871,514,947)){shown=false;action=PANEL_LOCK;}
                else if(!busy&&inside(x,y,756,505,936,610)){
                    if(network!=PANEL_UNKNOWN){action=network>=PANEL_ON?PANEL_WIFI_OFF:PANEL_WIFI_ON;busy=true;failed=false;}
                }else if(!busy&&inside(x,y,730,394,850,456)){action=PANEL_PROBE;busy=true;failed=false;}
                redraw=true;
            }
        }
        consumed=c->mode!=PASS;
        if(p->phase==kRemove||p->phase==kCancel)memset(c,0,sizeof(*c));
    }
    SystemPanelOps callbacks=ops;unlock_panel();
    for(unsigned i=0;i<replay_count;i++)if(callbacks.forward)callbacks.forward(&replay[i]);
    if(redraw)invalidate();
    if(action!=PANEL_NONE&&callbacks.request)callbacks.request(action);
    return consumed;
}
