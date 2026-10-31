#define _GNU_SOURCE
#undef NDEBUG
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <assert.h>
#include <stdint.h>
#include "embedder.h"
extern char **environ;
#define RAW(s) ((void)write(2,s,sizeof(s)-1))
int main(void){
    RAW("runtime-probe: entered main; no display/input/AOT initialization\n");
    /* Zig 0.13's generated glibc stubs alias object symbols. A non-PIC link
     * can emit one COPY relocation for stderr/stdin/stdout/environ together. */
    volatile uintptr_t err_addr=(uintptr_t)&stderr, in_addr=(uintptr_t)&stdin;
    volatile uintptr_t out_addr=(uintptr_t)&stdout, env_addr=(uintptr_t)&environ;
    if(err_addr==in_addr||err_addr==out_addr||err_addr==env_addr||in_addr==env_addr){
        RAW("FAIL: external libc object symbols alias after COPY relocation\n");
        return 78;
    }
    assert(stdin&&stdout&&stderr&&environ);
    assert(fileno(stdin)==0&&fileno(stdout)==1&&fileno(stderr)==2);
    assert(getenv("REEDEN_KOBO_DIR"));
    fprintf(stderr,"PASS: distinct libc streams/environment, fprintf and getenv\n");
    uint64_t now=FlutterEngineGetCurrentTime();assert(now>0);
    assert(FlutterEngineRunsAOTCompiledDartCode());
    fprintf(stderr,"PASS: engine constructors and time/AOT-mode queries; engine not started\n");
    return 0;
}
