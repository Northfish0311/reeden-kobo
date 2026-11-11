#define _GNU_SOURCE
#include "power_worker.h"
#include <errno.h>
#include <signal.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <sys/resource.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop_requested(int signal_number){(void)signal_number;stopping=1;}

uint64_t power_cover_due(uint64_t pending,uint64_t now){
    /* Cover updates can hasten the first submit, never postpone or re-arm it. */
    uint64_t due=now+100000000ULL;
    return pending&&due<pending?due:pending;
}
enum lock_result power_lock_result(int status,bool wake_requested,bool retried,bool lid_closed){
    if(wake_requested)return LOCK_RESUME;
    if(!WIFEXITED(status))return LOCK_KEEP;
    int code=WEXITSTATUS(status);
    if(code==0&&!lid_closed)return LOCK_RESUME;
    if(!retried&&((lid_closed&&(code==0||code==2))||code==3||code==75||code==76))return LOCK_RETRY;
    return LOCK_KEEP;
}

static pid_t start_helper(const char *path,const char *action_name){
    /* Linux clone with no exit signal creates a separate wait class. No
     * memory, file descriptor table or signal handlers are shared. Linux
     * resets the exit signal during exec, so this supervisor MUST NOT exec.
     * Only its own ordinary child executes the shell helper. Dart cannot
     * wait for that grandchild, or reap the non-SIGCHLD supervisor. */
    struct rlimit files;if(getrlimit(RLIMIT_NOFILE,&files))return -1;
    pid_t pid=(pid_t)syscall(SYS_clone,0,NULL,NULL,NULL,0);
    if(pid==0){
        /* Do not retain Flutter/Dart pipes, evdev grabs or display FDs. */
        for(rlim_t fd=3;fd<files.rlim_cur;fd++)close((int)fd);
        setpgid(0,0);
        struct sigaction action={0};sigemptyset(&action.sa_mask);
        action.sa_handler=SIG_DFL;sigaction(SIGCHLD,&action,NULL);
        action.sa_handler=stop_requested;
        sigaction(SIGTERM,&action,NULL);sigaction(SIGINT,&action,NULL);sigaction(SIGHUP,&action,NULL);
        pid_t helper=(pid_t)syscall(SYS_clone,SIGCHLD,NULL,NULL,NULL,0);
        if(helper==0){execl(path,path,action_name,(char*)NULL);_exit(127);}
        if(helper<0)_exit(127);
        int status=0;
        for(;;){
            if(stopping)kill(helper,SIGTERM);
            pid_t result=waitpid(helper,&status,0);
            if(result==helper)break;
            if(result<0&&errno==EINTR)continue;
            _exit(127);
        }
        _exit(WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status));
    }
    return pid;
}
pid_t power_worker_start(const char *path){return start_helper(path,"suspend");}
pid_t power_worker_restore_wifi(const char *path){return start_helper(path,"restore");}
pid_t power_worker_poll(pid_t pid,int *status){
    return waitpid(pid,status,WNOHANG|__WCLONE);
}
int power_worker_stop(pid_t pid){
    int status=0;pid_t result=power_worker_poll(pid,&status);
    if(result==pid||(result<0&&errno==ECHILD))return 0;
    if(result<0)return -1;
    if(kill(-pid,SIGTERM)<0&&kill(pid,SIGTERM)<0&&errno!=ESRCH)return -1;
    /* Never block UI shutdown on a helper restoring hardware or networking. */
    for(unsigned i=0;i<50;i++){
        result=power_worker_poll(pid,&status);
        if(result==pid||(result<0&&errno==ECHILD))return 0;
        usleep(100000);
    }
    if(kill(-pid,SIGKILL)<0&&kill(pid,SIGKILL)<0&&errno!=ESRCH)return -1;
    return 0;
}
