#include "cover.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

#define WORD_BITS (sizeof(unsigned long)*CHAR_BIT)
#define WORDS(max) ((max)/WORD_BITS+1)
static bool bit(const unsigned long *bits,unsigned n){return (bits[n/WORD_BITS]>>(n%WORD_BITS))&1;}
static void observe(Cover *c,int value,uint64_t now){
    if((value==0||value==1)&&value!=c->observed){
        c->observed=value;c->due=value==c->reported?0:now+150000000ULL;
    }
}
static void resync(Cover *c,uint64_t now){
    unsigned long bits[WORDS(KEY_MAX)]={0};
    unsigned long req=c->type==EV_SW?EVIOCGSW(sizeof(bits)):EVIOCGKEY(sizeof(bits));
    if(ioctl(c->fd,req,bits)>=0)observe(c,bit(bits,c->code),now);
    else {c->observed=-1;c->due=0;}
}
void cover_event(Cover *c,const struct input_event *e,uint64_t now){
    if(e->type==EV_SYN&&e->code==SYN_DROPPED){c->dropped=true;c->due=0;return;}
    if(c->dropped){
        if(e->type==EV_SYN&&e->code==SYN_REPORT){c->dropped=false;c->observed=-1;resync(c,now);}
        return;
    }
    if(e->type==c->type&&e->code==c->code)observe(c,e->value,now);
}
enum cover_edge cover_settled(Cover *c,uint64_t now){
    if(!c->due||now<c->due)return COVER_NONE;
    int previous=c->reported;c->reported=c->observed;c->due=0;
    if(c->reported==1)return COVER_CLOSED;
    return previous==1?COVER_OPEN:COVER_NONE;
}
static int source_type(int fd){
    struct input_id id;unsigned long switches[WORDS(SW_MAX)]={0},keys[WORDS(KEY_MAX)]={0};
    if(ioctl(fd,EVIOCGID,&id)<0||
       (id.bustype!=BUS_HOST&&id.bustype!=BUS_I2C&&id.bustype!=BUS_SPI))return -1;
    if(ioctl(fd,EVIOCGBIT(EV_SW,sizeof(switches)),switches)>=0&&bit(switches,SW_LID))return EV_SW;
    char name[80]={0};
    if(ioctl(fd,EVIOCGNAME(sizeof(name)-1),name)<0||ioctl(fd,EVIOCGBIT(EV_KEY,sizeof(keys)),keys)<0)return -1;
    /* Kobo's internal gpio keys use F1 for SleepCover; never accept a keyboard. */
    if(bit(keys,KEY_F1)&&!bit(keys,KEY_A)&&(!strcmp(name,"gpio-keys")||!strcmp(name,"ntx_event0")))return EV_KEY;
    return -1;
}
static bool same_node(int fd,int other){
    struct stat a,b;return other>=0&&!fstat(fd,&a)&&!fstat(other,&b)&&a.st_rdev==b.st_rdev;
}
void cover_close(Cover *c){
    if(c->fd>=0&&!c->shared_power)close(c->fd);
    *c=(Cover){.fd=-1,.observed=-1,.reported=-1};
}
void cover_seed(Cover *c){
    resync(c,0);
    /* Booting with the cover already shut is a state, not an edge: adopt what we
       observed as already reported and drop the timer, so main() cannot settle a
       COVER_CLOSED on its very first poll. */
    c->reported=c->observed;c->due=0;
}
void cover_open(Cover *c,int power_fd,int touch_fd){
    *c=(Cover){.fd=-1,.observed=-1,.reported=-1};
    for(unsigned n=0;n<32;n++){
        char path[48];snprintf(path,sizeof(path),"/dev/input/event%u",n);
        int fd=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_NOFOLLOW);if(fd<0)continue;
        int type=source_type(fd);
        if(type<0||same_node(fd,touch_fd)||(c->fd>=0&&type!=EV_SW)){close(fd);continue;}
        cover_close(c);c->type=type;c->code=type==EV_SW?SW_LID:KEY_F1;
        c->shared_power=same_node(fd,power_fd);
        if(c->shared_power){close(fd);c->fd=power_fd;}else c->fd=fd;
        fprintf(stderr,"[cover] candidate event%u %s\n",n,type==EV_SW?"SW_LID":"internal KEY_F1");
        if(type==EV_SW)break;
    }
    if(c->fd>=0)cover_seed(c);
    else fprintf(stderr,"[cover] no supported internal lid input; power key remains available\n");
}
