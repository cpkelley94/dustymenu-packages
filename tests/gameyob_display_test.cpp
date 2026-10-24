#include "framequeue.h"
#include "consolelayout.h"
#include <cassert>
#include <iostream>
#include <vector>

static GameYobFrameQueue queue;
static std::vector<int> calls;
static bool interruptActive;
static void second() { assert(!interruptActive);calls.push_back(2); }
static void first()
{
    assert(!interruptActive);calls.push_back(1);queue.enqueue(second,10);
    queue.service(10); // Reentrant same-frame servicing must not collapse the delay.
}
static void menu() { assert(!interruptActive);calls.push_back(3); }

int main()
{
    // Font and tile map must be disjoint and fit in the sub engine's 128 KiB.
    constexpr unsigned fontBegin=GAMEYOB_CONSOLE_TILE_BASE*16384;
    constexpr unsigned fontEnd=fontBegin+256*32;
    constexpr unsigned mapBegin=GAMEYOB_CONSOLE_MAP_BASE*2048;
    constexpr unsigned mapEnd=mapBegin+2048;
    static_assert(fontEnd<=mapBegin || mapEnd<=fontBegin,"Console map overlaps glyphs");
    static_assert(fontEnd<=128*1024 && mapEnd<=128*1024,"Console exceeds VRAM C");

    queue.enqueue(first,9);queue.enqueue(menu,9);queue.enqueue(nullptr,9);
    interruptActive=true; // The IRQ only reports a frame; no callbacks execute.
    assert(calls.empty());
    interruptActive=false;
    queue.service(10);
    assert((calls==std::vector<int>{1,3}));
    queue.service(10);
    assert((calls==std::vector<int>{1,3}));
    queue.service(11);
    assert((calls==std::vector<int>{1,3,2}));
    queue.enqueue(menu,11);
    queue.service(11);assert(calls.size()==3);
    queue.service(12);assert(calls.back()==3 && calls.size()==4);
    queue.enqueue(second,12);queue.service(UINT32_MAX);
    queue.enqueue(menu,UINT32_MAX);queue.service(0); // Frame-counter wrap still advances.
    assert(calls.size()==6 && calls.back()==3);
    GameYobFrameQueue late;
    late.enqueue(menu,20);late.service(20);assert(calls.size()==6);
    late.service(21);assert(calls.size()==7); // Enqueued after an IRQ: wait a full boundary.
    std::cout << "Foreground frame callbacks, multi-frame delays, and console VRAM layout passed\n";
}
