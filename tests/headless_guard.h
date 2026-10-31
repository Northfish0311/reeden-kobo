/* Diagnostic build only: never linked into the normal reader. */
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <linux/audit.h>
static void diagnostic_timeout(int sig){
    (void)sig;
    static const char message[]="[diagnostic] hard deadline reached; exiting\n";
    (void)write(2,message,sizeof(message)-1);_exit(124);
}
static int diagnostic_guard(void){
    /* Inherited by all engine threads/children; no network sockets or device
     * control ioctls. FIONREAD is a read-only byte-count query needed by
     * Dart's Process.runSync pipe reader; blocking it can itself hang Dart. */
    struct sock_filter code[]={
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,arch)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,AUDIT_ARCH_ARM,1,0),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,SYS_socket,0,3),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,args[0])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,AF_UNIX,5,0),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,SYS_ioctl,0,3),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,args[1])),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,FIONREAD,1,0),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW),
    };
    struct sock_fprog filter={.len=sizeof(code)/sizeof(code[0]),.filter=code};
    if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)||prctl(PR_SET_SECCOMP,SECCOMP_MODE_FILTER,&filter))return -1;
    int fd=socket(AF_INET,SOCK_STREAM,0);if(fd>=0){close(fd);errno=ENOTSUP;return -1;}
    if(errno!=EPERM)return -1;
    fd=socket(AF_INET6,SOCK_DGRAM,0);if(fd>=0){close(fd);errno=ENOTSUP;return -1;}
    if(errno!=EPERM)return -1;
    signal(SIGALRM,diagnostic_timeout);alarm(90);
    int pipes[2],available=-1;
    if(pipe(pipes))return -1;
    if(write(pipes[1],"x",1)!=1||ioctl(pipes[0],FIONREAD,&available)||available!=1)return -1;
    errno=0;if(ioctl(pipes[0],FBIOGET_VSCREENINFO,NULL)!=-1||errno!=EPERM)return -1;
    close(pipes[0]);close(pipes[1]);
    fprintf(stderr,"[diagnostic] seccomp active: no network/device control; pipe byte-count allowed; hard deadline 90s\n");
    return 0;
}
