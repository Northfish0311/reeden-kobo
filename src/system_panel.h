#pragma once
#include "embedder.h"
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

enum panel_action { PANEL_NONE, PANEL_PROBE, PANEL_WIFI_ON, PANEL_WIFI_OFF, PANEL_LOCK };
enum panel_wifi { PANEL_UNKNOWN, PANEL_OFF, PANEL_ON, PANEL_CONNECTED };
typedef struct {
    void (*invalidate)(void *);
    void (*request)(enum panel_action);
    void (*forward)(const FlutterPointerEvent *);
    void *userdata;
} SystemPanelOps;

void system_panel_init(SystemPanelOps);
void system_panel_available(bool, int cover_status);
void system_panel_network(enum panel_wifi, bool busy, bool failed);
void system_panel_hide(void);
bool system_panel_visible(void);
bool system_panel_pointer(FlutterPointerEvent *);
bool system_panel_compose(uint8_t *,size_t,unsigned,unsigned);
bool system_panel_redraw(uint8_t *,size_t,unsigned,unsigned);
void system_panel_destroy(void);
