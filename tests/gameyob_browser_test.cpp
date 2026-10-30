#include "browserpath.h"
#include <cassert>
#include <iostream>

int main()
{
    const char* roots[]={"/", "fat:/", "sd:/", "", nullptr};
    for(const char* root : roots)
        assert(gameyobParentEntry(root).empty());
    assert(gameyobParentEntry("/emulators")=="emulators");
    assert(gameyobParentEntry("fat:/emulators")=="emulators");
    assert(gameyobParentEntry("fat:/roms/gb")=="gb");
    assert(gameyobParentEntry("/roms/gb/")=="gb");
    assert(gameyobRomDirectory("fat:/roms/gb/Color test.gbc", "fat:/emulators")=="fat:/roms/gb/");
    assert(gameyobRomDirectory("/Color test.gbc", "fat:/emulators")=="/");
    assert(gameyobRomDirectory("Color test.gbc", "fat:/roms/gb")=="fat:/roms/gb");
    assert(gameyobRomDirectory("roms/Color test.gbc", "fat:/")=="fat:/roms/");
    assert(gameyobRomDirectory("../gb/Color test.gbc", "fat:/roms/gba")=="fat:/roms/gba/../gb/");
    assert(gameyobRomDirectory(nullptr, nullptr)=="/");
    assert(std::strcmp(gameyobFileExtension("Color test.gbc"), "gbc")==0);
    assert(std::strcmp(gameyobFileExtension("README"), "")==0);
    assert(std::strcmp(gameyobFileExtension(nullptr), "")==0);
    assert(std::strcmp(gameyobFileExtension("test."), "")==0);
    std::cout << "Browser parent paths, argv directories and extensionless files passed\n";
}
