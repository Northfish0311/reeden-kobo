#define _GNU_SOURCE
#undef NDEBUG
#include <assert.h>
#include <fcntl.h>
#include <linux/ioctl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>
#include "../src/cover.h"

static int level,kind=EV_KEY,bus=BUS_HOST,error;
static const char *device_name="gpio-keys";
static int fake_ioctl(int fd,unsigned long request,...){
    (void)fd;va_list args;va_start(args,request);void *p=va_arg(args,void *);va_end(args);
    if(error)return -1;
    unsigned long *bits=p;
    if(_IOC_NR(request)==_IOC_NR(EVIOCGID)){((struct input_id *)p)->bustype=bus;return 0;}
    if(_IOC_NR(request)==_IOC_NR(EVIOCGNAME(1))){strcpy(p,device_name);return 0;}
    unsigned n;
    if(_IOC_NR(request)==_IOC_NR(EVIOCGBIT(EV_SW,1))&&kind==EV_SW)n=SW_LID;
    else if(_IOC_NR(request)==_IOC_NR(EVIOCGBIT(EV_KEY,1))&&kind==EV_KEY)n=KEY_F1;
    else if(_IOC_NR(request)==_IOC_NR(EVIOCGSW(1))&&kind==EV_SW&&level)n=SW_LID;
    else if(_IOC_NR(request)==_IOC_NR(EVIOCGKEY(1))&&kind==EV_KEY&&level)n=KEY_F1;
    else return 0;
    bits[n/(8*sizeof(*bits))]|=1UL<<(n%(8*sizeof(*bits)));return 0;
}
#define ioctl fake_ioctl
#include "../src/cover.c"
#undef ioctl
static void send(Cover *c,int type,int code,int value,uint64_t at){
    struct input_event ev={.type=type,.code=code,.value=value};cover_event(c,&ev,at);
}
int main(void){
    const uint64_t ms=1000000ULL;
    for(int variant=0;variant<2;variant++){
        kind=variant?EV_SW:EV_KEY;bus=BUS_HOST;device_name="gpio-keys";
        assert(source_type(9)==kind);
        bus=BUS_USB;assert(source_type(9)<0);
        bus=BUS_BLUETOOTH;assert(source_type(9)<0);
        bus=BUS_HOST;device_name="keyboard";if(kind==EV_KEY)assert(source_type(9)<0);
        Cover c={.fd=9,.type=kind,.code=variant?SW_LID:KEY_F1,.observed=-1,.reported=-1};
        level=0;resync(&c,0);assert(cover_settled(&c,200*ms)==COVER_NONE);
        send(&c,kind,c.code,1,201*ms);send(&c,kind,c.code,0,230*ms);
        assert(cover_settled(&c,480*ms)==COVER_NONE); /* Bounce, not a real close. */
        send(&c,kind,c.code,1,500*ms);send(&c,kind,c.code,1,600*ms);
        send(&c,kind,c.code,2,630*ms); /* Auto-repeat cannot delay the edge. */
        assert(cover_settled(&c,649*ms)==COVER_NONE);
        assert(cover_settled(&c,650*ms)==COVER_CLOSED);
        assert(cover_settled(&c,1000*ms)==COVER_NONE);
        send(&c,EV_SYN,SYN_DROPPED,0,1100*ms);send(&c,kind,c.code,0,1200*ms);
        assert(cover_settled(&c,1400*ms)==COVER_NONE);
        level=0;send(&c,EV_SYN,SYN_REPORT,0,1500*ms);
        assert(cover_settled(&c,1660*ms)==COVER_OPEN);
        send(&c,EV_KEY,KEY_POWER,1,1700*ms);
        assert(cover_settled(&c,2000*ms)==COVER_NONE);
        error=1;resync(&c,2100*ms);assert(cover_settled(&c,2400*ms)==COVER_NONE);error=0;
        /* Boot with the cover already shut: seeding consumes the state instead of
           reporting a fresh close edge, and the next real open still fires. */
        c=(Cover){.fd=9,.type=kind,.code=variant?SW_LID:KEY_F1,.observed=-1,.reported=-1};
        level=1;cover_seed(&c);
        assert(cover_settled(&c,200*ms)==COVER_NONE);
        assert(cover_settled(&c,5000*ms)==COVER_NONE);
        level=0;send(&c,kind,c.code,0,5100*ms);
        assert(cover_settled(&c,5249*ms)==COVER_NONE);
        assert(cover_settled(&c,5250*ms)==COVER_OPEN);
        assert(cover_settled(&c,6000*ms)==COVER_NONE);
    }
    puts("PASS: internal Kobo/lid switch, keyboard rejection, close/open, chatter, dropped events and resync");
    return 0;
}
