#define _GNU_SOURCE
#include "power_worker.h"
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

static pid_t ordinary;
static void *foreign_reaper(void *unused){
    (void)unused;int status=0;pid_t result=wait(&status);
    if(result!=ordinary||!WIFEXITED(status)||WEXITSTATUS(status)!=7)
        fprintf(stderr,"foreign wait result=%d expected=%d status=%d errno=%d\n",result,ordinary,status,errno);
    assert(result==ordinary&&WIFEXITED(status)&&WEXITSTATUS(status)==7);
    return NULL;
}
int main(void){
    assert(power_cover_due(0,500)==0);
    assert(power_cover_due(900000000ULL,100)==100000100ULL);
    assert(power_cover_due(100000100ULL,900000000ULL)==100000100ULL);
    assert(power_lock_result(0,false,false,false)==LOCK_RESUME);
    assert(power_lock_result(0,false,false,true)==LOCK_RETRY);
    assert(power_lock_result(0,false,true,true)==LOCK_KEEP);
    assert(power_lock_result(0,true,true,true)==LOCK_RESUME);
    for(int code=1;code<=127;code++){
        assert(power_lock_result(code<<8,true,true,false)==LOCK_RESUME);
        assert(power_lock_result(code<<8,false,false,false)==((code==3||code==75||code==76)?LOCK_RETRY:LOCK_KEEP));
        assert(power_lock_result(code<<8,false,true,false)==LOCK_KEEP);
    }
    assert(power_lock_result(SIGTERM,false,false,false)==LOCK_KEEP);
    /* SSH shells may inherit an ignored SIGCHLD. Establish the VM's usual
     * child-reaping environment explicitly for the regression test. */
    assert(signal(SIGCHLD,SIG_DFL)!=SIG_ERR);
    char name[]="/tmp/reeden-worker-test-XXXXXX";int fd=mkstemp(name);assert(fd>=0);
    const char text[]="#!/bin/sh\nexit 3\n";
    assert(write(fd,text,sizeof(text)-1)==sizeof(text)-1);close(fd);assert(!chmod(name,0700));
    /* Reproduce the old wait-class collision deterministically. */
    ordinary=fork();assert(ordinary>=0);if(!ordinary)_exit(7);
    pthread_t reaper;assert(!pthread_create(&reaper,NULL,foreign_reaper,NULL));
    assert(!pthread_join(reaper,NULL));int status=0;errno=0;
    assert(waitpid(ordinary,&status,WNOHANG)==-1&&errno==ECHILD);
    /* A Dart-style reaper waits for an ordinary child while our isolated
     * helper finishes first. It must not steal our charging exit status. */
    ordinary=fork();assert(ordinary>=0);if(!ordinary){usleep(300000);_exit(7);}
    assert(!pthread_create(&reaper,NULL,foreign_reaper,NULL));
    pid_t worker=power_worker_start(name);assert(worker>0);
    usleep(100000);assert(!pthread_join(reaper,NULL));
    pid_t result=0;
    for(unsigned i=0;i<100&&!result;i++){result=power_worker_poll(worker,&status);if(!result)usleep(10000);}
    assert(result==worker&&WIFEXITED(status)&&WEXITSTATUS(status)==3);
    worker=power_worker_start("/no/such/reeden-test-helper");assert(worker>0);result=0;
    for(unsigned i=0;i<100&&!result;i++){result=power_worker_poll(worker,&status);if(!result)usleep(10000);}
    assert(result==worker&&WIFEXITED(status)&&WEXITSTATUS(status)==127);
    assert(!power_worker_stop(worker));unlink(name);
    puts("PASS: reproduced stolen ordinary child; isolated sleep worker survives foreign wait(), charging and exec-failure status retained");
    return 0;
}
