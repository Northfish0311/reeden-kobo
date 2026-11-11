#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <linux/input.h>

typedef struct {
    int fd,type,code,observed,reported;
    bool shared_power,dropped;
    uint64_t due;
} Cover;
enum cover_edge { COVER_NONE, COVER_OPEN, COVER_CLOSED };
void cover_open(Cover *,int power_fd,int touch_fd);
void cover_close(Cover *);
void cover_event(Cover *,const struct input_event *,uint64_t now);
enum cover_edge cover_settled(Cover *,uint64_t now);
