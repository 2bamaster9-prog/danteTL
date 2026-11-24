The bundled CPU and optional Vulkan engines use the llama.cpp revision
a956a852c9c8bc1fb07206364838ddef299178c0 vendored by abetlen/llama-cpp-python
v0.3.37. The optional NVIDIA engine uses JamePeng/llama-cpp-python v0.4.8+cu130.
The llama.cpp MIT notice is in llama.cpp.txt.
The Python binding's MIT notice is retained in its installed dist-info directory.

CPU wheels built with LLVM-MinGW may also contain LLVM libc++, libunwind,
OpenMP and MinGW runtime code. Their notices are included here. The verified
local build used llvm-mingw-20261104-ucrt-x86_64 from:
https://github.com/mstorsjo/llvm-mingw/releases/tag/20261104
The compiler itself is not distributed. MSVC builds may not use these libraries.
