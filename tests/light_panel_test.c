#include "light_panel.h"
#include "light_panel_art.h"
#undef NDEBUG
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

enum { W=1072,H=1448,ROW=W*4 };
static int raw_color=8,max_color=10,writes,invalidations;
static int choice=-1;
static void user_warmth(int raw){choice=raw;}
static uint8_t *frame;
static int read_fake(const char *path,int fallback){
    (void)fallback;
    if(strstr(path,"max_color"))return max_color;
    assert(!strcmp(path,"/sys/class/backlight/lm3630a_led/color"));return raw_color;
}
static int write_fake(const char *path,int value){
    /* No brightness path, real sysfs or input device can be accessed. */
    assert(!strcmp(path,"/sys/class/backlight/lm3630a_led/color"));
    assert(value>=0&&value<=10);raw_color=value;writes++;return 0;
}
static void invalidate_fake(void *u){
    (void)u;invalidations++;
    /* Re-entering here also checks that the callback releases the UI mutex. */
    assert(light_panel_redraw(frame,ROW,W,H));
}
static void make_panel(void){
    memset(frame,255,(size_t)ROW*H);
    const uint8_t *labels[]={light_label_0,light_label_1,light_label_2};
    for(unsigned i=0;i<3;i++)for(unsigned y=0;y<64;y++)for(unsigned x=0;x<66;x++){
        unsigned bit=y*66+x;
        if((labels[i][bit/8]>>(7-bit%8))&1){uint8_t *p=frame+(536+i*88+y)*ROW+(30+x)*4;p[0]=p[1]=p[2]=0;}
    }
}
static void point(FlutterPointerPhase phase,int id,double x,double y,bool consumed,double mapped_y){
    FlutterPointerEvent p={.struct_size=sizeof(p),.phase=phase,.device=id,.x=x,.y=y};
    assert(light_panel_pointer(&p)==consumed);assert(p.y==mapped_y);
}
int main(void){
    char root[]="/tmp/reeden-light-test-XXXXXX";assert(mkdtemp(root));
    char data[4096],file[4096];snprintf(data,sizeof(data),"%s/userdata",root);assert(!mkdir(data,0700));snprintf(file,sizeof(file),"%s/userdata/kobo-light.conf",root);
    frame=malloc((size_t)ROW*H);assert(frame);
    LightPanelOps ops={.read_number=read_fake,.write_number=write_fake,.invalidate=invalidate_fake,.user_warmth=user_warmth};
    light_panel_init(root,ops);assert(writes==0); /* Warmup has no hardware writes. */
    make_panel();assert(!light_panel_compose(frame,ROW,W,H));
    light_panel_acquired();assert(writes==1&&raw_color==8);
    assert(choice==-1);
    assert(light_row_offsets[11]==sizeof(light_row_rle));
    make_panel();assert(light_panel_compose(frame,ROW,W,H));
    /* The moved original frontlight must keep its original Flutter target. */
    FlutterPointerPhase phases[]={kAdd,kDown,kMove,kUp,kRemove};
    for(unsigned i=0;i<5;i++)point(phases[i],1,405,480,false,568);
    assert(writes==1);
    point(kAdd,2,916,568,true,568);point(kDown,2,916,568,true,568);
    assert(raw_color==0&&invalidations==1);
    point(kMove,2,236,568,true,568);assert(raw_color==10&&invalidations==2);
    point(kUp,2,236,568,true,568);point(kRemove,2,236,568,true,568);
    assert(choice==10);
    FILE *f=fopen(file,"r");int saved=-1;assert(f&&fscanf(f,"warmth=%d",&saved)==1&&saved==0);fclose(f);
    point(kAdd,3,1004,568,true,568);point(kDown,3,1004,568,true,568);
    point(kUp,3,1004,568,true,568);point(kRemove,3,1004,568,true,568);assert(raw_color==9);
    /* A plain reader frame must not expose or intercept the extra row. */
    memset(frame,255,(size_t)ROW*H);assert(!light_panel_compose(frame,ROW,W,H));
    for(unsigned i=0;i<5;i++)point(phases[i],4,500,568,false,568);
    int old_writes=writes;raw_color=3;light_panel_init(root,ops);assert(writes==old_writes);
    light_panel_acquired();assert(raw_color==9); /* Saved 10% is restored. */
    max_color=100;old_writes=writes;light_panel_init(root,ops);light_panel_acquired();assert(writes==old_writes);
    make_panel();assert(!light_panel_compose(frame,ROW,W,H));
    unlink(file);rmdir(data);rmdir(root);free(frame);
    puts("PASS: exact-panel detection, cold/warm range and inversion, native-touch consumption, frontlight remap, persistence, warmup guard, unsupported-device fallback; no hardware accessed");
    return 0;
}
