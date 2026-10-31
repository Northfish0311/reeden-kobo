#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <unistd.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <sys/user.h>
#include <signal.h>
/* Reads registers only from an explicitly identified headless diagnostic.
 * PTRACE_SEIZE/INTERRUPT avoids sending process-wide SIGSTOP. */
int main(int argc,char **argv){
    if(argc!=2)return 64;int pid=atoi(argv[1]);if(pid<=1)return 64;
    char path[256],buf[16384];snprintf(path,sizeof(path),"/proc/%d/environ",pid);
    FILE *f=fopen(path,"rb");if(!f)return 1;size_t n=fread(buf,1,sizeof(buf)-1,f);fclose(f);buf[n]=0;
    int allowed=0;for(size_t i=0;i<n;){size_t len=strlen(buf+i);if(!strncmp(buf+i,"REEDEN_DIAGNOSTIC_DATA=/mnt/onboard/.adds/reeden-kobo/diagnostics/",sizeof("REEDEN_DIAGNOSTIC_DATA=/mnt/onboard/.adds/reeden-kobo/diagnostics/")-1))allowed=1;i+=len+1;}
    if(!allowed){fputs("Refusing non-diagnostic process\n",stderr);return 65;}
    alarm(3);snprintf(path,sizeof(path),"/proc/%d/task",pid);DIR *d=opendir(path);if(!d)return 1;struct dirent *ent;
    while((ent=readdir(d))){int tid=atoi(ent->d_name);if(tid<=1)continue;snprintf(path,sizeof(path),"/proc/%d/task/%d/comm",pid,tid);f=fopen(path,"r");if(!f)continue;buf[0]=0;fgets(buf,sizeof(buf),f);fclose(f);if(strcmp(buf,"io.flutter.ui\n"))continue;
        if(ptrace(PTRACE_SEIZE,tid,0,0)||ptrace(PTRACE_INTERRUPT,tid,0,0)){perror("ptrace attach");return 2;}
        int status;if(waitpid(tid,&status,__WALL)!=tid||!WIFSTOPPED(status)){ptrace(PTRACE_DETACH,tid,0,0);return 3;}
        struct user_regs regs;if(ptrace(PTRACE_GETREGS,tid,0,&regs)){perror("registers");ptrace(PTRACE_DETACH,tid,0,0);return 4;}
        printf("UI pid=%d tid=%d",pid,tid);for(int i=0;i<18;i++)printf(" r%d=%08lx",i,regs.uregs[i]);puts("");
        /* ARM frame pointers: read only a bounded chain of address pairs. */
        unsigned long fp=regs.uregs[11];for(int i=0;i<12&&fp>=regs.uregs[13]&&fp-regs.uregs[13]<1024*1024;i++){
            unsigned long next=ptrace(PTRACE_PEEKDATA,tid,(void*)fp,0),lr=ptrace(PTRACE_PEEKDATA,tid,(void*)(fp+4),0);
            printf("frame %d fp=%08lx next=%08lx lr=%08lx\n",i,fp,next,lr);if(next<=fp||next>fp+1024*1024)break;fp=next;
        }
        if(ptrace(PTRACE_DETACH,tid,0,0)){perror("detach");return 5;}
    }
    closedir(d);return 0;
}
