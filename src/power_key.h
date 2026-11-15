#ifndef REEDEN_POWER_KEY_H
#define REEDEN_POWER_KEY_H
#include <stdbool.h>
#include <linux/input.h>

typedef struct { bool down,dropped,ignore_wake_press; } PowerKey;

/* True only for a release observed after a trustworthy press. */
bool power_key_event(PowerKey *key,int fd,const struct input_event *event);
void power_key_end_wake_drain(PowerKey *key);
#endif
