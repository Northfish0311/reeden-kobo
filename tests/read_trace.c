#define _GNU_SOURCE
#define _LARGEFILE64_SOURCE
#include <dlfcn.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <sys/syscall.h>
#include <stdint.h>
#include <fcntl.h>
#include <sys/wait.h>
/* Diagnostic-only preload: preserve read semantics; record metadata, never bytes. */
static ssize_t (*real_read)(int,void*,size_t);
static int enabled;
static int trace_fd=-1;
static __thread unsigned long eof_count;
static __thread unsigned long pread_count;
__attribute__((constructor)) static void init(void){
    real_read=dlsym(RTLD_NEXT,"read");
    enabled=getenv("REEDEN_DIAGNOSTIC_DATA")!=NULL;
    if(enabled)trace_fd=fcntl(2,F_DUPFD_CLOEXEC,80);
}
int execvp(const char *path,char *const argv[]){
    static int(*next)(const char*,char *const[]);if(!next)next=dlsym(RTLD_NEXT,"execvp");
    if(enabled){char b[1200];int n=snprintf(b,sizeof(b),"[exec-trace] pid=%ld path=%s arg1=%s arg2=%s\n",(long)getpid(),path,argv[0]&&argv[1]?argv[1]:"",argv[0]&&argv[1]&&argv[2]?argv[2]:"");(void)syscall(SYS_write,trace_fd,b,n>0&&(size_t)n<sizeof(b)?(size_t)n:sizeof(b)-1);}
    int r=next(path,argv),e=errno;
    if(enabled){char b[100];int n=snprintf(b,sizeof(b),"[exec-trace] failed errno=%d\n",e);(void)syscall(SYS_write,trace_fd,b,n);}
    errno=e;return r;
}
pid_t wait(int *status){
    static pid_t(*next)(int*);if(!next)next=dlsym(RTLD_NEXT,"wait");
    pid_t p=next(status);int e=errno;
    if(enabled&&p>0){char b[100];int n=snprintf(b,sizeof(b),"[exec-trace] reaped pid=%ld status=%x\n",(long)p,status?*status:0);(void)syscall(SYS_write,trace_fd,b,n);}
    errno=e;return p;
}
ssize_t pread64(int fd,void *buf,size_t count,off64_t offset){
    static ssize_t(*next)(int,void*,size_t,off64_t);if(!next)next=dlsym(RTLD_NEXT,"pread64");
    ssize_t r=next(fd,buf,count,offset);int e=errno;unsigned long k=++pread_count;
    if(enabled&&(k<=20||k%100000==0)){
        char path[64],target[512],b[800];snprintf(path,sizeof(path),"/proc/self/fd/%d",fd);ssize_t n=readlink(path,target,sizeof(target)-1);if(n<0)n=0;target[n]=0;
        int len=snprintf(b,sizeof(b),"[pread-trace] tid=%ld fd=%d bytes=%u offset=%lld result=%ld calls=%lu target=%s\n",syscall(SYS_gettid),fd,(unsigned)count,(long long)offset,(long)r,k,target);(void)syscall(SYS_write,trace_fd,b,len);
    }errno=e;return r;
}
ssize_t read(int fd,void *buf,size_t count){
    if(!real_read)real_read=dlsym(RTLD_NEXT,"read");
    if(!real_read){errno=ENOSYS;return -1;}
    ssize_t n=real_read(fd,buf,count);int saved=errno;
    if(enabled&&n==0&&count){
        unsigned long k=++eof_count;
        if(k<=20||k%100000==0){
            char link[80],target[1024],line[1400];
            snprintf(link,sizeof(link),"/proc/self/fd/%d",fd);
            ssize_t len=readlink(link,target,sizeof(target)-1);
            if(len<0)len=0;target[len]=0;
            int size=snprintf(line,sizeof(line),"[read-trace] tid=%ld fd=%d count=%u eof=%lu target=%s\n",syscall(SYS_gettid),fd,(unsigned)count,k,target);
            if(size>0)(void)syscall(SYS_write,2,line,(size_t)size<sizeof(line)?(size_t)size:sizeof(line)-1);
        }
    }
    errno=saved;return n;
}
