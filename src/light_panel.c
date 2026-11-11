#include "light_panel.h"
#include "light_panel_art.h"
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

#define COLOR_PATH "/sys/class/backlight/lm3630a_led/color"
#define MAX_COLOR_PATH "/sys/class/backlight/lm3630a_led/max_color"
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static LightPanelOps ops;
static bool enabled,acquired,active,unsaved;
static int level; /* 0 = cold; 10 = warm. Hardware scale is inverted. */
static char settings[4096];
typedef struct {int32_t id;unsigned mode;bool slider;} PanelContact;
static PanelContact contacts[16];

void light_panel_init(const char *root,LightPanelOps callbacks){
    pthread_mutex_lock(&lock);ops=callbacks;
    enabled=ops.read_number&&ops.write_number&&ops.read_number(MAX_COLOR_PATH,-1)==10;
    int raw=enabled?ops.read_number(COLOR_PATH,-1):-1;
    enabled=enabled&&raw>=0&&raw<=10;level=enabled?10-raw:0;
    active=false;acquired=false;unsaved=false;memset(contacts,0,sizeof(contacts));
    snprintf(settings,sizeof(settings),"%s/userdata/kobo-light.conf",root);
    FILE *f=fopen(settings,"r");int saved=-1;
    if(f){if(fscanf(f,"warmth=%d",&saved)==1&&saved>=0&&saved<=100&&saved%10==0)level=saved/10;fclose(f);}
    pthread_mutex_unlock(&lock);
}
void light_panel_acquired(void){
    pthread_mutex_lock(&lock);
    if(enabled){acquired=true;if(ops.write_number(COLOR_PATH,10-level))fprintf(stderr,"[light] restore warmth failed: %s\n",strerror(errno));}
    pthread_mutex_unlock(&lock);
}
static bool label_matches(const uint8_t *pixels,size_t stride,unsigned top,const uint8_t *mask){
    unsigned wrong=0;
    for(unsigned y=0;y<64;y++)for(unsigned x=0;x<66;x++){
        unsigned bit=y*66+x;const uint8_t *p=pixels+(top+y)*stride+(30+x)*4;
        bool black=p[0]<128&&p[1]<128&&p[2]<128;
        bool expected=(mask[bit/8]>>(7-bit%8))&1;
        if(black!=expected&&++wrong>32)return false;
    }
    return true;
}
static void paint_row(uint8_t *pixels,size_t stride){
    uint32_t at=light_row_offsets[level],end=light_row_offsets[level+1];unsigned position=0;
    while(at+2<end){
        unsigned count=light_row_rle[at]|((unsigned)light_row_rle[at+1]<<8);uint8_t gray=light_row_rle[at+2];at+=3;
        while(count--&&position<1072*88){
            uint8_t *p=pixels+(532+position/1072)*stride+(position%1072)*4;
            p[0]=p[1]=p[2]=gray;p[3]=255;position++;
        }
    }
}
bool light_panel_compose(uint8_t *pixels,size_t stride,unsigned width,unsigned height){
    pthread_mutex_lock(&lock);
    active=enabled&&acquired&&width==1072&&height==1448&&stride>=1072*4&&
        label_matches(pixels,stride,536,light_label_0)&&
        label_matches(pixels,stride,624,light_label_1)&&
        label_matches(pixels,stride,712,light_label_2);
    if(active){
        /* Extend the existing display sheet upward by one row. Its remaining
         * controls stay at their original coordinates. Keep floating book
         * controls attached to the shortened viewport, with input remapped. */
        memmove(pixels+176*stride,pixels+264*stride,356*stride);
        paint_row(pixels,stride);
    }
    bool result=active;pthread_mutex_unlock(&lock);return result;
}
bool light_panel_redraw(uint8_t *pixels,size_t stride,unsigned width,unsigned height){
    pthread_mutex_lock(&lock);bool result=active&&width==1072&&height==1448&&stride>=1072*4;
    if(result)paint_row(pixels,stride);
    pthread_mutex_unlock(&lock);return result;
}
static void save_locked(void){
    if(!unsaved)return;
    char temp[4120];snprintf(temp,sizeof(temp),"%s.new",settings);
    FILE *f=fopen(temp,"w");if(!f)return;
    int written=fprintf(f,"warmth=%d\n",level*10);int closed=fclose(f);
    if(written>0&&!closed&&!rename(temp,settings))unsaved=false;
}
bool light_panel_pointer(FlutterPointerEvent *p){
    bool invalidate=false,consumed=false;
    pthread_mutex_lock(&lock);
    PanelContact *c=NULL;
    for(unsigned i=0;i<16;i++)if(contacts[i].mode&&contacts[i].id==p->device){c=&contacts[i];break;}
    if(!c&&(p->phase==kAdd||p->phase==kDown)&&active){
        unsigned mode=p->y>=532&&p->y<620?1:p->y>=176&&p->y<532?2:0;
        if(mode)for(unsigned i=0;i<16;i++)if(!contacts[i].mode){c=&contacts[i];*c=(PanelContact){.id=p->device,.mode=mode};break;}
    }
    if(c&&c->mode==1){
        consumed=true;
        int value=level;
        if(p->phase==kDown){
            c->slider=p->x>=200&&p->x<=952;
            if(p->x>=112&&p->x<=184)value--;
            else if(p->x>=968&&p->x<=1040)value++;
        }
        if(c->slider&&(p->phase==kDown||p->phase==kMove))value=(int)((p->x-236)/68+0.5);
        if(value<0)value=0;if(value>10)value=10;
        if(value!=level&&enabled&&acquired){
            if(!ops.write_number(COLOR_PATH,10-value)){level=value;unsaved=true;invalidate=true;fprintf(stderr,"[light] warmth=%d\n",level*10);}
            else fprintf(stderr,"[light] set warmth failed: %s\n",strerror(errno));
        }
        if(p->phase==kUp||p->phase==kCancel||p->phase==kRemove){
            if(unsaved&&ops.user_warmth)ops.user_warmth(10-level);
            save_locked();
        }
    }else if(c&&c->mode==2)p->y+=88;
    if(c&&(p->phase==kRemove||p->phase==kCancel))memset(c,0,sizeof(*c));
    LightPanelOps callbacks=ops;pthread_mutex_unlock(&lock);
    if(invalidate&&callbacks.invalidate)callbacks.invalidate(callbacks.userdata);
    return consumed;
}
