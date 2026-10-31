#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include "embedder.h"

typedef struct {
    int (*read_number)(const char *,int);
    int (*write_number)(const char *,int);
    void (*invalidate)(void *);
    void *userdata;
} LightPanelOps;

void light_panel_init(const char *,LightPanelOps);
void light_panel_acquired(void);
bool light_panel_compose(uint8_t *,size_t,unsigned,unsigned);
bool light_panel_redraw(uint8_t *,size_t,unsigned,unsigned);
/* Consumes native-control contacts, or remaps shifted contacts for Flutter. */
bool light_panel_pointer(FlutterPointerEvent *);
