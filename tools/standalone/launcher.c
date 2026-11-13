/* A relocatable GUI launcher. No Python installation, PATH edits or elevation required. */
#ifndef UNICODE
#define UNICODE
#endif
#define _UNICODE
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t directory[32768], python[32768], command[32768];
    DWORD count = GetModuleFileNameW(NULL, directory, 32768);
    if (!count || count >= 32768) return 1;
    wchar_t *slash = wcsrchr(directory, L'\\');
    if (!slash) return 1;
    *slash = L'\0';
    int n = swprintf(python, 32768, L"%ls\\_internal\\python\\pythonw.exe", directory);
    int m = swprintf(command, 32768,
        L"\"%ls\" -I -B \"%ls\\_internal\\app\\bootstrap.py\" %ls",
        python, directory, arguments);
    if (n < 0 || m < 0) return 1;
    STARTUPINFOW startup = {0};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process = {0};
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, directory, &startup, &process)) {
        MessageBoxW(NULL,
            L"DanteJP could not start. Extract the entire ZIP first and keep the _internal "
            L"folder beside DanteJP.exe.", L"DanteJP", MB_OK | MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
