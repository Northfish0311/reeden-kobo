#include "power_key.h"
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>

bool power_key_event(PowerKey *key,int fd,const struct input_event *event){
    if(event->type==EV_SYN&&event->code==SYN_DROPPED){
        key->down=false;key->dropped=true;
        fprintf(stderr,"[power] SYN_DROPPED; waiting for SYN_REPORT\n");
        return false;
    }
    if(key->dropped){
        /* evdev requires discarding the incomplete packet before querying state. */
        if(event->type==EV_SYN&&event->code==SYN_REPORT){
            const unsigned word_bits=sizeof(unsigned long)*CHAR_BIT;
            unsigned long bits[KEY_MAX/(sizeof(unsigned long)*CHAR_BIT)+1]={0};
            if(ioctl(fd,EVIOCGKEY(sizeof(bits)),bits)<0){
                fprintf(stderr,"[power] key state resync failed: %s; waiting for next SYN_REPORT\n",strerror(errno));
            }else{
                bool held=(bits[KEY_POWER/word_bits]>>(KEY_POWER%word_bits))&1;
                key->down=held&&!key->ignore_wake_press;
                key->dropped=false;key->ignore_wake_press=false;
                fprintf(stderr,"[power] key state resynced at SYN_REPORT down=%d\n",held?1:0);
            }
        }
        return false;
    }
    if(event->type!=EV_KEY||event->code!=KEY_POWER)return false;
    if(event->value==1)key->down=true;
    if(event->value==0&&key->down){key->down=false;return true;}
    return false;
}

void power_key_end_wake_drain(PowerKey *key){
    /* A wake press, even one recovered at a later report, must not relock. */
    key->down=false;
    key->ignore_wake_press=key->dropped;
}
