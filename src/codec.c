#include "codec.h"
#include <string.h>
#include <limits.h>
static int take(Reader *r, void *out, size_t n) {
    if (r->error || n > r->n-r->pos) { r->error=1; return 0; }
    if(out) memcpy(out,r->p+r->pos,n);
    r->pos+=n; return 1;
}
static unsigned byte(Reader *r) { uint8_t b=0; take(r,&b,1); return b; }
static size_t size(Reader *r) {
    unsigned b=byte(r); uint16_t s=0; uint32_t l=0;
    if(b<254) return b;
    if(b==254) { take(r,&s,2); return s; }
    take(r,&l,4); return l;
}
static int align_r(Reader *r, size_t n) { return take(r,NULL,(n-r->pos%n)%n); }
static int value_depth(Reader *r, Value *v, unsigned depth) {
    if(depth>24) { r->error=1; return 0; }
    memset(v,0,sizeof(*v)); v->type=(int)byte(r);
    size_t n=0, elem=1;
    switch(v->type) {
      case 0: case 1: case 2: v->integer=v->type==1; break;
      case 3: { int32_t i=0; take(r,&i,4); v->integer=i; break; }
      case 4: take(r,&v->integer,8); break;
      case 6: align_r(r,8); take(r,&v->real,8); break;
      case 5: case 7:
        n=size(r); if(n>=sizeof(v->string)) { r->error=1; break; }
        take(r,v->string,n); break;
      case 12: case 13: {
        n=size(r); if(n>4096) { r->error=1; break; }
        if(v->type==13)n*=2;
        for(size_t i=0;i<n && !r->error;i++) { Value tmp; value_depth(r,&tmp,depth+1); }
        break;
      }
      case 8: case 9: case 10: case 11: case 14:
        n=size(r); elem=v->type==8?1:(v->type==9||v->type==14?4:8);
        if(v->type!=8)align_r(r,elem);
        if(n>SIZE_MAX/elem)r->error=1; else take(r,NULL,n*elem); break;
      default: r->error=1;
    }
    return !r->error;
}
int read_value(Reader *r, Value *v) { return value_depth(r,v,0); }
int read_method(Reader *r, char *s, size_t n) {
    Value v; if(!read_value(r,&v)||v.type!=7||strlen(v.string)>=n)return 0;
    strcpy(s,v.string); return 1;
}
int read_argument(Reader r, const char *key, Value *v) {
    if(!key)return read_value(&r,v);
    if(byte(&r)!=13)return 0;
    size_t n=size(&r); if(n>4096)return 0;
    for(size_t i=0;i<n;i++) {
        Value k; if(!read_value(&r,&k)||!read_value(&r,v))return 0;
        if(k.type==7&&!strcmp(k.string,key))return 1;
    }
    return 0;
}
void w_byte(Writer *w,unsigned x) { if(w->n==sizeof(w->data)){w->error=1;return;} w->data[w->n++]=(uint8_t)x; }
static void bytes(Writer *w,const void *p,size_t n) { if(n>sizeof(w->data)-w->n){w->error=1;return;} memcpy(w->data+w->n,p,n);w->n+=n; }
static void wsize(Writer *w,unsigned n) { if(n<254)w_byte(w,n);else if(n<=65535){uint16_t s=n;w_byte(w,254);bytes(w,&s,2);}else{w_byte(w,255);bytes(w,&n,4);} }
void w_null(Writer *w){w_byte(w,0);}
void w_bool(Writer *w,int b){w_byte(w,b?1:2);}
void w_int(Writer *w,int64_t i){if(i>=INT32_MIN&&i<=INT32_MAX){int32_t n=i;w_byte(w,3);bytes(w,&n,4);}else{w_byte(w,4);bytes(w,&i,8);}}
void w_string(Writer *w,const char *s){if(!s){w_null(w);return;}size_t n=strlen(s);if(n>UINT_MAX){w->error=1;return;}w_byte(w,7);wsize(w,(unsigned)n);bytes(w,s,n);}
void w_list(Writer *w,unsigned n){w_byte(w,12);wsize(w,n);}
void w_map(Writer *w,unsigned n){w_byte(w,13);wsize(w,n);}
