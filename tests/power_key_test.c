#define _GNU_SOURCE
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <linux/ioctl.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include "../src/power_key.h"
#include "../src/cover.h"

static bool pressed,lid_closed,query_error;
static unsigned key_queries;
static int fake_ioctl(int fd,unsigned long request,void *out){
    assert(fd==9);
    unsigned long *bits=out;
    if(request==EVIOCGKEY((KEY_MAX/(sizeof(unsigned long)*8)+1)*sizeof(unsigned long))){
        key_queries++;
        if(query_error){errno=EIO;return -1;}
        if(pressed)bits[KEY_POWER/(sizeof(*bits)*8)]|=1UL<<(KEY_POWER%(sizeof(*bits)*8));
        return 0;
    }
    if(_IOC_NR(request)==_IOC_NR(EVIOCGSW(1))){
        if(lid_closed)bits[0]|=1UL<<SW_LID;
        return 0;
    }
    assert(0);return -1;
}
#define ioctl fake_ioctl
#include "../src/power_key.c"
#include "../src/cover.c"
#undef ioctl

static bool send_key(PowerKey *key,int type,int code,int value){
    struct input_event event={.type=type,.code=code,.value=value};
    return power_key_event(key,9,&event);
}
int main(void){
    PowerKey key={0};
    assert(!send_key(&key,EV_KEY,KEY_POWER,0));
    assert(!send_key(&key,EV_KEY,KEY_POWER,1));
    assert(!send_key(&key,EV_KEY,KEY_POWER,2));
    assert(send_key(&key,EV_KEY,KEY_POWER,0));
    assert(!send_key(&key,EV_KEY,KEY_POWER,0));
    assert(!send_key(&key,EV_KEY,KEY_F1,1)&&!key.down);

    for(unsigned held=0;held<2;held++){
        key=(PowerKey){.down=true};pressed=held;key_queries=0;
        assert(!send_key(&key,EV_SYN,SYN_DROPPED,0));
        assert(key.dropped&&!key.down&&key_queries==0);
        /* Stale press/release events, including across read() calls, do nothing. */
        assert(!send_key(&key,EV_KEY,KEY_POWER,1));
        assert(!send_key(&key,EV_KEY,KEY_POWER,0));
        assert(!send_key(&key,EV_SYN,SYN_DROPPED,0)&&key_queries==0);
        assert(!send_key(&key,EV_SYN,SYN_REPORT,0));
        assert(key_queries==1&&!key.dropped&&key.down==pressed);
        if(!held)assert(!send_key(&key,EV_KEY,KEY_POWER,1));
        assert(send_key(&key,EV_KEY,KEY_POWER,0));
        assert(!send_key(&key,EV_KEY,KEY_POWER,0));
    }

    query_error=true;pressed=false;key_queries=0;
    assert(!send_key(&key,EV_SYN,SYN_DROPPED,0));
    assert(!send_key(&key,EV_SYN,SYN_REPORT,0));
    assert(key.dropped&&!key.down&&key_queries==1);
    assert(!send_key(&key,EV_KEY,KEY_POWER,1));
    assert(!send_key(&key,EV_KEY,KEY_POWER,0));
    query_error=false;pressed=true;
    assert(!send_key(&key,EV_SYN,SYN_REPORT,0));
    assert(!key.dropped&&key.down&&key_queries==2);
    assert(send_key(&key,EV_KEY,KEY_POWER,0));

    for(unsigned partial=0;partial<2;partial++){
        key=(PowerKey){0};pressed=true;key_queries=0;
        assert(!send_key(&key,EV_SYN,SYN_DROPPED,0));
        if(!partial)assert(!send_key(&key,EV_SYN,SYN_REPORT,0));
        power_key_end_wake_drain(&key);
        if(partial)assert(!send_key(&key,EV_SYN,SYN_REPORT,0));
        assert(key_queries==1&&!key.dropped&&!key.down);
        assert(!send_key(&key,EV_KEY,KEY_POWER,2));
        assert(!send_key(&key,EV_KEY,KEY_POWER,0)); /* Wake release cannot relock. */
        assert(!send_key(&key,EV_KEY,KEY_POWER,1));
        assert(send_key(&key,EV_KEY,KEY_POWER,0));
    }

    Cover cover={.fd=9,.type=EV_SW,.code=SW_LID,.observed=0,.reported=0,.shared_power=true};
    struct input_event shared[]={
        {.type=EV_SYN,.code=SYN_DROPPED},
        {.type=EV_KEY,.code=KEY_POWER,.value=1},
        {.type=EV_KEY,.code=KEY_POWER,.value=0},
        {.type=EV_SW,.code=SW_LID,.value=0},
        {.type=EV_SYN,.code=SYN_REPORT}
    };
    key=(PowerKey){0};pressed=false;lid_closed=true;
    for(unsigned i=0;i<sizeof(shared)/sizeof(*shared);i++){
        cover_event(&cover,&shared[i],1000000000ULL);
        assert(!power_key_event(&key,9,&shared[i]));
    }
    assert(cover_settled(&cover,1200000000ULL)==COVER_CLOSED);
    assert(!key.dropped&&!key.down);
    assert(!send_key(&key,EV_KEY,KEY_POWER,1));
    assert(send_key(&key,EV_KEY,KEY_POWER,0));
    puts("PASS: power key releases, SYN_REPORT resync, stale packets, ioctl failure retry and shared lid input; no hardware accessed");
    return 0;
}
