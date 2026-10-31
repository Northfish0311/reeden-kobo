#pragma once
#include <stdbool.h>
#include <sys/types.h>

/* A non-SIGCHLD child is invisible to Dart's process-wide wait(). */
pid_t power_worker_start(const char *path);
pid_t power_worker_poll(pid_t pid,int *status);
int power_worker_stop(pid_t pid);
