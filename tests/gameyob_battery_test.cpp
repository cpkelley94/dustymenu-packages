#include "batteryfile.h"
#include <algorithm>
#include <cassert>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

static bool denyOpen,failWrite,failRead,failSync;
static unsigned creates,closes;
extern "C" FILE* __real_fopen(const char*,const char*);
extern "C" int __real_fclose(FILE*);
extern "C" size_t __real_fwrite(const void*,size_t,size_t,FILE*);
extern "C" size_t __real_fread(void*,size_t,size_t,FILE*);
extern "C" int __real_fsync(int);
extern "C" FILE* __wrap_fopen(const char* path,const char* mode)
{
    if(denyOpen && !std::strcmp(mode,"r+b")) { errno=EACCES;return NULL; }
    if(!std::strcmp(mode,"w+b")) ++creates;
    return __real_fopen(path,mode);
}
extern "C" int __wrap_fclose(FILE* file)
{
    assert(file); // Reproduces the old startup bug if a null close returns.
    ++closes;
    return __real_fclose(file);
}
extern "C" size_t __wrap_fwrite(const void* data,size_t size,size_t count,FILE* file)
{
    assert(file);
    if(failWrite) { errno=ENOSPC;return 0; }
    return __real_fwrite(data,size,count,file);
}
extern "C" size_t __wrap_fread(void* data,size_t size,size_t count,FILE* file)
{
    assert(file);
    if(failRead) { errno=EIO;return 0; }
    return __real_fread(data,size,count,file);
}
extern "C" int __wrap_fsync(int fd)
{
    if(failSync) { errno=EIO;return -1; }
    return __real_fsync(fd);
}

static std::string contents(const std::string& path)
{
    std::ifstream file(path,std::ios::binary);
    return {std::istreambuf_iterator<char>(file),std::istreambuf_iterator<char>()};
}
static void put(const std::string& path,const std::string& data)
{
    std::ofstream file(path,std::ios::binary);file.write(data.data(),data.size());assert(file);
}

int main(int argc,char** argv)
{
    assert(argc==2);
    const std::string root=argv[1];
    for(size_t banks : {size_t(1),size_t(4),size_t(8),size_t(16)})
    {
        const auto path=root+"/new-"+std::to_string(banks)+".sav";
        std::vector<unsigned char> ram(banks*8192,0xa5),rtc(48,0xa5);
        FILE* file=NULL;
        assert(gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),rtc.data(),rtc.size(),file));
        assert(file && std::all_of(ram.begin(),ram.end(),[](auto value) { return value==0; }));
        assert(std::all_of(rtc.begin(),rtc.end(),[](auto value) { return value==0; }));
        assert(contents(path)==std::string(ram.size()+rtc.size(),'\0'));
        std::fill(ram.begin(),ram.end(),0x42);std::fill(rtc.begin(),rtc.end(),0x7c);
        assert(fseek(file,0,SEEK_SET)==0);
        assert(fwrite(ram.data(),1,ram.size(),file)==ram.size());
        assert(fwrite(rtc.data(),1,rtc.size(),file)==rtc.size());
        assert(fclose(file)==0);file=NULL;
        std::fill(ram.begin(),ram.end(),0);std::fill(rtc.begin(),rtc.end(),0);
        assert(gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),rtc.data(),rtc.size(),file));
        assert(std::all_of(ram.begin(),ram.end(),[](auto value) { return value==0x42; }));
        assert(std::all_of(rtc.begin(),rtc.end(),[](auto value) { return value==0x7c; }));
        assert(fclose(file)==0);
    }
    std::vector<unsigned char> ram(32768,0xa5),rtc(48,0xa5);
    FILE* file=NULL;
    const std::string path=root+"/existing.sav";
    const std::string prefix="existing save prefix";
    put(path,prefix);
    assert(gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),rtc.data(),rtc.size(),file));
    assert(fclose(file)==0);
    assert(contents(path)==prefix+std::string(ram.size()+rtc.size()-prefix.size(),'\0'));
    put(path,std::string(ram.size(),'R')); // Legacy SRAM file without an RTC trailer.
    assert(gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),rtc.data(),rtc.size(),file));
    assert(fclose(file)==0);
    assert(contents(path)==std::string(ram.size(),'R')+std::string(rtc.size(),'\0'));
    const std::string larger(ram.size()+rtc.size()+127,'X');
    put(path,larger);
    assert(gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),rtc.data(),rtc.size(),file));
    assert(fclose(file)==0 && contents(path)==larger); // Never truncate extra save data.

    unsigned oldCreates=creates,oldCloses=closes;
    denyOpen=true;
    assert(!gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),NULL,0,file));
    denyOpen=false;
    assert(!file && creates==oldCreates && closes==oldCloses && contents(path)==larger);
    assert(!gameyobOpenBatterySave((root+"/missing/child.sav").c_str(),ram.data(),ram.size(),NULL,0,file));
    assert(!file);
    put(path,prefix);failWrite=true;
    assert(!gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),NULL,0,file));
    failWrite=false;
    assert(!file && contents(path)==prefix);
    failSync=true;
    assert(!gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),NULL,0,file));
    failSync=false;
    assert(!file && contents(path).substr(0,prefix.size())==prefix);
    failRead=true;
    assert(!gameyobOpenBatterySave(path.c_str(),ram.data(),ram.size(),NULL,0,file));
    failRead=false;
    assert(!file);
    std::cout << "Battery save creation, RAM/RTC reload, extension, preservation, and I/O faults passed\n";
}
