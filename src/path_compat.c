#define _GNU_SOURCE
#define _LARGEFILE64_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <sys/syscall.h>
/* Compatibility covers storage paths, child tools, and CPU worker sizing.
 * No license/identity calls are intercepted. Official AOT bytes stay unchanged. */
static char appdir[PATH_MAX],storage[PATH_MAX],certs[PATH_MAX];
static const char *path(const char *p,char out[PATH_MAX]){
    if(p&&certs[0]&&(!strcmp(p,"/etc/ssl/certs/ca-certificates.crt")||!strcmp(p,"/etc/pki/tls/certs/ca-bundle.crt")||!strcmp(p,"/etc/ssl/cert.pem")))return certs;
    if(p&&storage[0]&&!strncmp(p,"/mnt/us",7)&&(p[7]=='/'||p[7]==0)){
        int n=snprintf(out,PATH_MAX,"%s%s",storage,p+7);if(n<0||n>=PATH_MAX){errno=ENAMETOOLONG;return NULL;}return out;
    }
    return p;
}
__attribute__((constructor))static void init(void){
    const char *p=getenv("REEDEN_KOBO_DIR");if(p){snprintf(appdir,sizeof(appdir),"%s",p);snprintf(storage,sizeof(storage),"%s/storage",p);snprintf(certs,sizeof(certs),"%s/certs/ca-certificates.crt",p);}
}
#define RESOLVE(name) static __typeof__(&name) next; if(!next)next=(__typeof__(&name))dlsym(RTLD_NEXT,#name)
int open(const char *p,int flags,...){RESOLVE(open);mode_t mode=0;if(flags&O_CREAT){va_list a;va_start(a,flags);mode=va_arg(a,int);va_end(a);}char b[PATH_MAX];p=path(p,b);if(!p)return -1;return next(p,flags,mode);}
int open64(const char *p,int flags,...){RESOLVE(open64);mode_t mode=0;if(flags&O_CREAT){va_list a;va_start(a,flags);mode=va_arg(a,int);va_end(a);}char b[PATH_MAX];p=path(p,b);if(!p)return -1;return next(p,flags,mode);}
int openat(int fd,const char *p,int flags,...){RESOLVE(openat);mode_t mode=0;if(flags&O_CREAT){va_list a;va_start(a,flags);mode=va_arg(a,int);va_end(a);}char b[PATH_MAX];p=path(p,b);if(!p)return -1;return next(fd,p,flags,mode);}
int openat64(int fd,const char *p,int flags,...){RESOLVE(openat64);mode_t mode=0;if(flags&O_CREAT){va_list a;va_start(a,flags);mode=va_arg(a,int);va_end(a);}char b[PATH_MAX];p=path(p,b);if(!p)return -1;return next(fd,p,flags,mode);}
FILE *fopen(const char *p,const char *m){RESOLVE(fopen);char b[PATH_MAX];p=path(p,b);return p?next(p,m):NULL;}
FILE *fopen64(const char *p,const char *m){RESOLVE(fopen64);char b[PATH_MAX];p=path(p,b);return p?next(p,m):NULL;}
DIR *opendir(const char *p){RESOLVE(opendir);char b[PATH_MAX];p=path(p,b);return p?next(p):NULL;}
int access(const char *p,int mode){RESOLVE(access);char b[PATH_MAX];p=path(p,b);return p?next(p,mode):-1;}
int faccessat(int fd,const char *p,int mode,int flags){RESOLVE(faccessat);char b[PATH_MAX];p=path(p,b);return p?next(fd,p,mode,flags):-1;}
int mkdir(const char *p,mode_t mode){RESOLVE(mkdir);char b[PATH_MAX];p=path(p,b);return p?next(p,mode):-1;}
int mkdirat(int fd,const char *p,mode_t mode){RESOLVE(mkdirat);char b[PATH_MAX];p=path(p,b);return p?next(fd,p,mode):-1;}
int unlinkat(int fd,const char *p,int flags){RESOLVE(unlinkat);char b[PATH_MAX];p=path(p,b);return p?next(fd,p,flags):-1;}
int renameat(int fd,const char *p,int other,const char *q){RESOLVE(renameat);char a[PATH_MAX],b[PATH_MAX];p=path(p,a);q=path(q,b);return p&&q?next(fd,p,other,q):-1;}
/* ARM glibc 2.31 expects stat ABI version 3. Zig wrappers pass 0; the
 * structures are ARM-compatible, but fstatat explicitly rejects version 0.
 * The public stat/fstatat symbols do not exist in this libc until 2.33. */
int __fxstatat(int v,int fd,const char *p,struct stat *s,int flags){static int(*fn)(int,int,const char*,struct stat*,int);if(!fn)fn=dlsym(RTLD_NEXT,"__fxstatat");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(v==0?3:v,fd,p,s,flags):-1;}
int __fxstatat64(int v,int fd,const char *p,struct stat64 *s,int flags){static int(*fn)(int,int,const char*,struct stat64*,int);if(!fn)fn=dlsym(RTLD_NEXT,"__fxstatat64");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(v==0?3:v,fd,p,s,flags):-1;}
int unlink(const char *p){RESOLVE(unlink);char b[PATH_MAX];p=path(p,b);return p?next(p):-1;}
int rmdir(const char *p){RESOLVE(rmdir);char b[PATH_MAX];p=path(p,b);return p?next(p):-1;}
int rename(const char *p,const char *q){RESOLVE(rename);char a[PATH_MAX],b[PATH_MAX];p=path(p,a);q=path(q,b);return p&&q?next(p,q):-1;}
int stat(const char *p,struct stat *s){static int(*fn)(int,const char*,struct stat*);if(!fn)fn=dlsym(RTLD_NEXT,"__xstat");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(3,p,s):-1;}
int lstat(const char *p,struct stat *s){static int(*fn)(int,const char*,struct stat*);if(!fn)fn=dlsym(RTLD_NEXT,"__lxstat");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(3,p,s):-1;}
int stat64(const char *p,struct stat64 *s){static int(*fn)(int,const char*,struct stat64*);if(!fn)fn=dlsym(RTLD_NEXT,"__xstat64");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(3,p,s):-1;}
int lstat64(const char *p,struct stat64 *s){static int(*fn)(int,const char*,struct stat64*);if(!fn)fn=dlsym(RTLD_NEXT,"__lxstat64");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(3,p,s):-1;}
int fstatat(int fd,const char *p,struct stat *s,int flags){static int(*fn)(int,int,const char*,struct stat*,int);if(!fn)fn=dlsym(RTLD_NEXT,"__fxstatat");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(3,fd,p,s,flags):-1;}
int fstatat64(int fd,const char *p,struct stat64 *s,int flags){static int(*fn)(int,int,const char*,struct stat64*,int);if(!fn)fn=dlsym(RTLD_NEXT,"__fxstatat64");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(3,fd,p,s,flags):-1;}
int __xstat(int v,const char *p,struct stat *s){static int(*fn)(int,const char*,struct stat*);if(!fn)fn=dlsym(RTLD_NEXT,"__xstat");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(v==0?3:v,p,s):-1;}
int __lxstat(int v,const char *p,struct stat *s){static int(*fn)(int,const char*,struct stat*);if(!fn)fn=dlsym(RTLD_NEXT,"__lxstat");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(v==0?3:v,p,s):-1;}
int __xstat64(int v,const char *p,struct stat64 *s){static int(*fn)(int,const char*,struct stat64*);if(!fn)fn=dlsym(RTLD_NEXT,"__xstat64");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(v==0?3:v,p,s):-1;}
int __lxstat64(int v,const char *p,struct stat64 *s){static int(*fn)(int,const char*,struct stat64*);if(!fn)fn=dlsym(RTLD_NEXT,"__lxstat64");char b[PATH_MAX];p=path(p,b);return p&&fn?fn(v==0?3:v,p,s):-1;}
ssize_t readlink(const char *p,char *out,size_t n){RESOLVE(readlink);char b[PATH_MAX];p=path(p,b);return p?next(p,out,n):-1;}
ssize_t readlinkat(int fd,const char *p,char *out,size_t n){RESOLVE(readlinkat);char b[PATH_MAX];p=path(p,b);return p?next(fd,p,out,n):-1;}
int chdir(const char *p){RESOLVE(chdir);char b[PATH_MAX];p=path(p,b);return p?next(p):-1;}
/* Child system executables must use the Kobo loader + libraries, not our private
 * libc. Use a stack-only environment filter, suitable for Dart's fork/exec path. */
static int clean_exec(const char *file,char *const argv[],char *const envp[]){
    char mapped[PATH_MAX];const char *base=strrchr(file,'/');base=base?base+1:file;
    if(appdir[0]&&(!strcmp(base,"lipc-get-prop")||!strcmp(base,"lipc-set-prop"))){if(snprintf(mapped,sizeof(mapped),"%s/bin/%s",appdir,base)>=(int)sizeof(mapped)){errno=ENAMETOOLONG;return -1;}file=mapped;}
    char *env[2048];size_t j=0;
    for(size_t i=0;envp&&envp[i];i++){
        if(!strncmp(envp[i],"LD_PRELOAD=",11)||!strncmp(envp[i],"LD_LIBRARY_PATH=",16)||!strncmp(envp[i],"LD_AUDIT=",9))continue;
        if(j>=2047){errno=E2BIG;return -1;}env[j++]=envp[i];
    }env[j]=NULL;
    return (int)syscall(SYS_execve,file,argv,env);
}
int execve(const char *p,char *const a[],char *const e[]){return clean_exec(p,a,e);}
extern char **environ;
int execv(const char *p,char *const a[]){return clean_exec(p,a,environ);}
int execvp(const char *p,char *const a[]){
    if(strchr(p,'/'))return clean_exec(p,a,environ);
    const char *search=getenv("PATH");if(!search)search="/usr/bin:/bin";
    int denied=0;while(*search){const char *end=strchr(search,':');size_t n=end?(size_t)(end-search):strlen(search);char b[PATH_MAX];if(n+strlen(p)+2<sizeof(b)){memcpy(b,search,n);b[n]='/';strcpy(b+n+1,p);clean_exec(b,a,environ);if(errno==EACCES)denied=1;else if(errno!=ENOENT&&errno!=ENOTDIR)return -1;}if(!end)break;search=end+1;}
    errno=denied?EACCES:ENOENT;return -1;
}

/* Reeden's worker initialization stalls when Dart reports a single online
 * CPU. Clara Colour has two configured CPUs but normally parks CPU1. Report
 * configured capacity to the app; leave CPU hotplug and governors unchanged.
 * Only widen a one-CPU online result when the real configured count is >=2. */
long sysconf(int name){
    RESOLVE(sysconf);
    long value=next(name);
    if(name==_SC_NPROCESSORS_ONLN&&value==1){
        long configured=next(_SC_NPROCESSORS_CONF);
        if(configured>=2)return configured;
    }
    return value;
}
