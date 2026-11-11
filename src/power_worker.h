#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <sys/types.h>

/* A non-SIGCHLD child is invisible to Dart's process-wide wait(). */
pid_t power_worker_start(const char *path);
pid_t power_worker_restore_wifi(const char *path);
pid_t power_worker_poll(pid_t pid,int *status);
int power_worker_stop(pid_t pid);

enum lock_result { LOCK_KEEP, LOCK_RETRY, LOCK_RESUME };
enum lock_result power_lock_result(int wait_status, bool wake_requested, bool retried, bool lid_closed);
uint64_t power_cover_due(uint64_t pending, uint64_t now);
