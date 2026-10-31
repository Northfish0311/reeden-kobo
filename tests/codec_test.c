#include "codec.h"
#undef NDEBUG
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
int main(void){
    /* Independent StandardMessageCodec fixtures; int64 is deliberately unaligned. */
    const uint8_t call[]={7,7,'r','e','f','r','e','s','h',13,1,7,7,'d','e','l','a','y','M','s',3,250,0,0,0};
    Reader r={call,sizeof(call),0,0};char method[32];Value v;
    assert(read_method(&r,method,sizeof(method))&&!strcmp(method,"refresh"));
    assert(read_argument(r,"delayMs",&v)&&v.type==3&&v.integer==250);
    const uint8_t integer[]={4,0,0,0,0,1,0,0,0};r=(Reader){integer,sizeof(integer),0,0};
    assert(read_value(&r,&v)&&v.integer==INT64_C(4294967296)&&r.pos==9);
    const uint8_t real[]={6,0,0,0,0,0,0,0,0,0,0,0,0,0,248,63};r=(Reader){real,sizeof(real),0,0};
    assert(read_value(&r,&v)&&v.real==1.5&&r.pos==16);
    for(size_t n=1;n<sizeof(integer);n++){r=(Reader){integer,n,0,0};assert(!read_value(&r,&v)&&r.error);}
    const uint8_t bad[]={7,255,255,255,255,255};r=(Reader){bad,sizeof(bad),0,0};assert(!read_value(&r,&v));
    uint8_t deep[80];for(int i=0;i<39;i++){deep[i*2]=12;deep[i*2+1]=1;}deep[78]=0;
    r=(Reader){deep,79,0,0};assert(!read_value(&r,&v)&&r.error);
    Writer w={0};w_byte(&w,0);w_int(&w,INT64_C(4294967296));
    assert(w.n==10&&!w.error&&w.data[0]==0&&w.data[1]==4&&!memcmp(w.data+2,integer+1,8));
    char large[20000];memset(large,'x',sizeof(large)-1);large[sizeof(large)-1]=0;w_string(&w,large);assert(w.error);
    puts("PASS: method/map fixture, int64 and double alignment, truncation, size/depth bounds, success envelope, output overflow");return 0;
}
