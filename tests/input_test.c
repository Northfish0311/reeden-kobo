#include "kobo.h"
#include <linux/input.h>
#undef NDEBUG
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <poll.h>
static FlutterPointerEvent got[128];static size_t count;
uint64_t monotonic_ns(void){return 1000000;}
FlutterEngineResult FlutterEngineSendPointerEvent(FlutterEngine e,const FlutterPointerEvent *p,size_t n){(void)e;assert(count+n<128);memcpy(got+count,p,n*sizeof(*p));count+=n;return kSuccess;}
static void event(int fd,int type,int code,int value){struct input_event e={.type=type,.code=code,.value=value};assert(write(fd,&e,sizeof(e))==sizeof(e));}
static void contact(int fd,int id,int x,int y){event(fd,EV_ABS,ABS_MT_TRACKING_ID,id);event(fd,EV_ABS,ABS_MT_POSITION_X,x);event(fd,EV_ABS,ABS_MT_POSITION_Y,y);event(fd,EV_SYN,SYN_MT_REPORT,0);}
int main(void){
    int fd[2];assert(!pipe2(fd,O_NONBLOCK));Touch t={.fd=fd[0],.max_x=1447,.max_y=1071,.current={.id=-1}};for(int i=0;i<16;i++)t.contacts[i].id=-1;
    contact(fd[1],3,0,0);contact(fd[1],8,1447,1071);event(fd[1],EV_SYN,SYN_REPORT,0);touch_process(&t,(FlutterEngine)1,1072,1448);
    assert(count==4&&got[0].phase==kAdd&&got[1].phase==kDown&&got[0].x==1071&&got[0].y==0&&got[2].x==0&&got[2].y==1447);
    event(fd[1],EV_SYN,SYN_REPORT,0);touch_process(&t,(FlutterEngine)1,1072,1448);assert(count==8&&got[4].phase==kUp&&got[5].phase==kRemove);
    t.slots=true;memset(t.report,0,sizeof(t.report));event(fd[1],EV_ABS,ABS_MT_SLOT,1);event(fd[1],EV_ABS,ABS_MT_TRACKING_ID,12);event(fd[1],EV_ABS,ABS_MT_POSITION_X,200);event(fd[1],EV_ABS,ABS_MT_POSITION_Y,300);event(fd[1],EV_SYN,SYN_REPORT,0);touch_process(&t,(FlutterEngine)1,1072,1448);assert(count==10&&got[9].phase==kDown);
    event(fd[1],EV_SYN,SYN_DROPPED,0);event(fd[1],EV_SYN,SYN_REPORT,0);touch_process(&t,(FlutterEngine)1,1072,1448);assert(count==12&&got[10].phase==kCancel&&got[11].phase==kRemove);
    touch_close(&t,(FlutterEngine)1);assert(t.fd==-1);
    struct pollfd waiting={.fd=t.fd,.events=POLLIN};
    assert(poll(&waiting,1,20)==0&&waiting.revents==0);
    /* A second close must not close the new owner of the reused descriptor. */
    int replacement=open("/dev/null",O_RDONLY);assert(replacement>=0);
    assert(replacement==fd[0]);touch_close(&t,(FlutterEngine)1);
    assert(fcntl(replacement,F_GETFD)>=0);close(replacement);close(fd[1]);
    puts("PASS: Type A/B input, dropped events, locked polling and idempotent close with reused FD; synthetic devices only");return 0;
}
