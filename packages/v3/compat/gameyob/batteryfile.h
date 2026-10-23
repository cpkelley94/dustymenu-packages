// SPDX-License-Identifier: MIT
// Checked battery-save initialization for the pinned GameYob source build.
#pragma once
#include <stdio.h>
#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <unistd.h>

// The caller owns the returned open stream. On failure no stream is returned.
// Existing save bytes and any extra trailer are preserved; only missing bytes
// are zero-filled. A failed open is never closed or treated as an empty save.
inline bool gameyobOpenBatterySave(const char* path,unsigned char* ram,size_t ramBytes,
    void* rtc,size_t rtcBytes,FILE*& result)
{
    result=NULL;
    const size_t maximum=static_cast<size_t>(LONG_MAX);
    if(!path || !*path || (ramBytes && !ram) || (rtcBytes && !rtc) ||
       ramBytes>maximum || rtcBytes>maximum-ramBytes || ramBytes+rtcBytes==0)
    {
        errno=EINVAL;
        return false;
    }
    FILE* file=fopen(path,"r+b");
    if(!file)
    {
        if(errno!=ENOENT) return false; // Do not truncate an inaccessible existing save.
        file=fopen(path,"w+b");
        if(!file) return false;
    }
    auto fail=[&]() {
        const int error=errno ? errno : EIO;
        fclose(file); // file is always non-null here.
        errno=error;
        return false;
    };
    if(fseek(file,0,SEEK_END)!=0) return fail();
    const long length=ftell(file);
    if(length<0) return fail();
    const size_t needed=ramBytes+rtcBytes;
    if(static_cast<size_t>(length)<needed)
    {
        unsigned char zeros[256]={};
        size_t missing=needed-static_cast<size_t>(length);
        while(missing)
        {
            const size_t count=missing<sizeof(zeros) ? missing : sizeof(zeros);
            if(fwrite(zeros,1,count,file)!=count) return fail();
            missing-=count;
        }
        if(fflush(file)!=0 || fsync(fileno(file))!=0) return fail();
    }
    if(fseek(file,0,SEEK_SET)!=0) return fail();
    if((ramBytes && fread(ram,1,ramBytes,file)!=ramBytes) ||
       (rtcBytes && fread(rtc,1,rtcBytes,file)!=rtcBytes))
    {
        if(!ferror(file)) errno=EIO;
        return fail();
    }
    result=file;
    return true;
}
