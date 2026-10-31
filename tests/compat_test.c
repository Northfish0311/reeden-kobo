#define _GNU_SOURCE
#define _LARGEFILE64_SOURCE
#undef NDEBUG
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <errno.h>
#include <dlfcn.h>
int main(void){
    write(2,"compat: begin\n",14); const char *root=getenv("REEDEN_KOBO_DIR");assert(root);
    char dir[200],file[240],renamed[240],physical[4096];snprintf(dir,sizeof(dir),"/mnt/us/.kobo-compat-test-%d",getpid());
    write(2,"compat: mkdir\n",14); assert(mkdirat(AT_FDCWD,dir,0700)==0);snprintf(file,sizeof(file),"%s/a",dir);snprintf(renamed,sizeof(renamed),"%s/b",dir);
    write(2,"compat: open\n",13); int fd=open64(file,O_WRONLY|O_CREAT|O_EXCL,0600);assert(fd>=0&&write(fd,"probe",5)==5);close(fd);
    snprintf(physical,sizeof(physical),"%s/storage%s/a",root,dir+7);struct stat64 s;assert(!stat64(physical,&s)&&s.st_size==5);
    write(2,"compat: fstatat\n",16); errno=0; int r=fstatat64(AT_FDCWD,file,&s,0); if(r)perror("fstatat64"); if(s.st_size!=5)write(2,"size mismatch\n",14); assert(!r&&s.st_size==5);struct stat small; assert(!stat(file,&small)&&small.st_size==5); assert(!fstatat(AT_FDCWD,file,&small,0)&&small.st_size==5);
    int(*direct_stat64)(const char*,struct stat64*)=dlsym(RTLD_DEFAULT,"stat64"); assert(direct_stat64&&!direct_stat64(file,&s)&&s.st_size==5);
    write(2,"compat: rename\n",15); assert(!renameat(AT_FDCWD,file,AT_FDCWD,renamed));
    fd=openat64(AT_FDCWD,renamed,O_RDONLY);char buf[6]={0};assert(fd>=0&&read(fd,buf,5)==5&&!strcmp(buf,"probe"));close(fd);
    assert(!unlinkat(AT_FDCWD,renamed,0)&&!unlinkat(AT_FDCWD,dir,AT_REMOVEDIR));
    write(2,"compat: cert\n",13); FILE *cert=fopen("/etc/ssl/certs/ca-certificates.crt","r");char line[80];assert(cert&&fgets(line,sizeof(line),cert)&&strstr(line,"BEGIN CERTIFICATE"));fclose(cert);
    char preload[4096],libs[4096];snprintf(preload,sizeof(preload),"%s/lib/libreeden_kobo_compat.so",root);snprintf(libs,sizeof(libs),"%s/runtime",root);
    assert(!setenv("LD_PRELOAD",preload,1)&&!setenv("LD_LIBRARY_PATH",libs,1));
    write(2,"compat: fork\n",13); pid_t pid=fork();assert(pid>=0);
    if(!pid){char *a[]={"sh","-c","test -z \"$LD_PRELOAD\" && test -z \"$LD_LIBRARY_PATH\"",NULL};execvp("/bin/sh",a);_exit(127);}
    int status;assert(waitpid(pid,&status,0)==pid&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
    unsetenv("LD_PRELOAD");unsetenv("LD_LIBRARY_PATH");
    puts("PASS: private storage mapping/openat/stat/rename/unlink, public CA lookup, clean system-child exec; temporary probe removed");return 0;
}
