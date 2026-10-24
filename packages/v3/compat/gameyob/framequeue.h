// SPDX-License-Identifier: MIT
#pragma once
#include <stdint.h>
#include <vector>

// Foreground only: IRQ handlers report frame numbers, but never touch this
// queue or run callbacks which may allocate, print, or access the filesystem.
class GameYobFrameQueue
{
public:
    using Task=void(*)();
    void enqueue(Task task,uint32_t frame) { if(task) pending.push_back({task,frame}); }
    void service(uint32_t frame)
    {
        if(started && frame==lastFrame) return;
        started=true;
        lastFrame=frame;
        std::vector<Entry> ready;
        ready.swap(pending);
        for(const Entry& entry : ready)
        {
            // A foreground caller can enqueue after this frame's IRQ. Never
            // run that callback until a subsequent frame boundary has passed.
            if(entry.queuedFrame==frame) pending.push_back(entry);
            else entry.task();
        }
    }
private:
    struct Entry { Task task;uint32_t queuedFrame; };
    std::vector<Entry> pending;
    uint32_t lastFrame=0;
    bool started=false;
};
