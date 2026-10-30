// SPDX-License-Identifier: MIT
#pragma once
#include <cstring>
#include <string>

// getcwd() may return either /folder or fat:/folder. A top-level folder
// still has a basename, and a device root has no parent entry to select.
inline std::string gameyobParentEntry(const char* cwd)
{
    std::string path=cwd ? cwd : "";
    while(!path.empty() && path.back()=='/') path.pop_back();
    if(path.empty() || path.back()==':') return "";
    const auto slash=path.find_last_of('/');
    const auto colon=path.find_last_of(':');
    return path.substr(slash!=std::string::npos ? slash+1 :
                       colon!=std::string::npos ? colon+1 : 0);
}

inline std::string gameyobRomDirectory(const char* filename,const char* cwd)
{
    std::string base=cwd && *cwd ? cwd : "/";
    std::string path=filename ? filename : "";
    const auto slash=path.find_last_of('/');
    if(slash==std::string::npos) return base;
    path.resize(slash+1);
    if(path.front()=='/' || path.find(":/")!=std::string::npos) return path;
    if(base.back()!='/') base+='/';
    return base+path;
}

inline const char* gameyobFileExtension(const char* filename)
{
    const char* dot=filename ? std::strrchr(filename,'.') : nullptr;
    return dot ? dot+1 : "";
}
