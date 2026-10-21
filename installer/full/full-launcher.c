/*
 * GENESIS Final — FULL setup launcher (native Win32, no dependencies).
 *
 * Why this exists (2026-10-21, YZ order "the final setup must be complete,
 * without any shortage"): the Tauri/NSIS installer cannot contain the
 * 5.85 GB brain model (makensis is 32-bit; the package would exceed its
 * 4 GB ceiling), so the FULL setup is a 7-Zip SFX whose RunProgram is THIS
 * launcher. Double-click the one setup file and everything lands:
 *
 *   1. closes any running GENESIS processes (upgrade-safe),
 *   2. runs the bundled app installer (setup\GENESIS-Full-Setup.exe /S),
 *   3. copies payload\genesis_369_v1_Q5_K_M.gguf into
 *      %LOCALAPPDATA%\com.genesis.final\models\ WITH VISIBLE PROGRESS,
 *   4. verifies the model SHA-256 against the W14 pin (BCrypt),
 *   5. launches the installed app.
 *
 * app/src-tauri/src/brain.rs ensure_model() then finds the verified GGUF
 * already in models_dir and boots with ZERO network downloads.
 *
 * Build (cross, on the build VM):  zig cc -target x86_64-windows-gnu -O2
 *   -s -o full-launcher.exe full-launcher.c -lbcrypt
 */

#include <windows.h>
#include <tlhelp32.h>
#include <bcrypt.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

#define MODEL_NAME_W L"genesis_369_v1_Q5_K_M.gguf"
#define MODEL_SIZE_BYTES 5851112800ULL
#define MODEL_SHA256_HEX "1a762d6d2c9cd7c34d2497dad1cbb67b4f77f43dccb8cd1efe7f925b9a7e4371"

static int fail(const char *step, const char *detail) {
    printf("\nERROR at step [%s]: %s\n", step, detail);
    printf("Nothing was hidden — report this message. Press Enter to close.\n");
    fflush(stdout);
    (void)getchar();
    return 1;
}

/* ---------- helpers ---------- */

static void path_join(wchar_t *out, size_t cap, const wchar_t *a, const wchar_t *b) {
    _snwprintf(out, cap, L"%s\\%s", a, b);
    out[cap - 1] = L'\0';
}

static int file_exists(const wchar_t *p) {
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

static unsigned long long file_size(const wchar_t *p) {
    WIN32_FILE_ATTRIBUTE_DATA d;
    if (!GetFileAttributesExW(p, GetFileExInfoStandard, &d)) return 0;
    return ((unsigned long long)d.nFileSizeHigh << 32) | d.nFileSizeLow;
}

static void env_dir(const wchar_t *name, wchar_t *out, size_t cap) {
    DWORD n = GetEnvironmentVariableW(name, out, (DWORD)cap);
    if (n == 0 || n >= cap) out[0] = L'\0';
}

/* Kill processes whose image path lives under any GENESIS install dir,
   plus the llama-server sidecars by name (they only exist from us). */
static int contains_ci(const wchar_t *hay, const wchar_t *needle) {
    size_t hn = wcslen(hay), nn = wcslen(needle);
    if (nn == 0 || nn > hn) return 0;
    for (size_t i = 0; i + nn <= hn; i++) {
        size_t j = 0;
        while (j < nn && towlower(hay[i + j]) == towlower(needle[j])) j++;
        if (j == nn) return 1;
    }
    return 0;
}

static void kill_genesis_processes(const wchar_t *install_dir) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return;
    PROCESSENTRY32W pe;
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            if (pe.th32ProcessID == GetCurrentProcessId()) continue;
            HANDLE proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE,
                                      FALSE, pe.th32ProcessID);
            if (!proc) continue;
            wchar_t path[1024];
            DWORD sz = (DWORD)(sizeof(path) / sizeof(path[0]));
            int kill = 0;
            if (QueryFullProcessImageNameW(proc, 0, path, &sz)) {
                if (install_dir[0] && contains_ci(path, install_dir)) kill = 1;
                if (contains_ci(path, L"llama-server-")) kill = 1;
            }
            if (!kill && (contains_ci(pe.szExeFile, L"llama-server-"))) kill = 1;
            if (kill) TerminateProcess(proc, 0);
            CloseHandle(proc);
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
}

static int run_and_wait(const wchar_t *exe, const wchar_t *args) {
    wchar_t cmd[2048];
    _snwprintf(cmd, sizeof(cmd) / sizeof(cmd[0]), L"\"%s\" %s", exe, args);
    cmd[(sizeof(cmd) / sizeof(cmd[0])) - 1] = L'\0';
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(NULL, cmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi))
        return -1;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}

/* Find the app exe inside an install dir: first *.exe that is not the
   uninstaller, preferring a name containing "GENESIS". */
static int find_app_exe_in(const wchar_t *dir, wchar_t *out, size_t cap) {
    wchar_t pat[1200], fallback[1200];
    fallback[0] = L'\0';
    _snwprintf(pat, sizeof(pat) / sizeof(pat[0]), L"%s\\*.exe", dir);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        if (contains_ci(fd.cFileName, L"uninstall")) continue;
        path_join(out, cap, dir, fd.cFileName);
        if (contains_ci(fd.cFileName, L"GENESIS")) {
            FindClose(h);
            return 1;
        }
        if (!fallback[0]) path_join(fallback, sizeof(fallback) / sizeof(fallback[0]), dir, fd.cFileName);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    if (fallback[0]) {
        wcsncpy(out, fallback, cap - 1);
        out[cap - 1] = L'\0';
        return 1;
    }
    return 0;
}

/* ---------- SHA-256 (BCrypt) with progress ---------- */

static int sha256_hex(const wchar_t *path, char *out_hex, size_t out_cap, int show_progress) {
    if (out_cap < 65) return -1;
    BCRYPT_ALG_HANDLE alg = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    DWORD obj_len = 0, ret = 0;
    unsigned char digest[32];
    int rc = -1;
    FILE *f = NULL;

    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, 0) != 0) goto done;
    if (BCryptGetProperty(alg, BCRYPT_OBJECT_LENGTH, (PUCHAR)&obj_len, sizeof(obj_len), &ret, 0) != 0) goto done;
    unsigned char *obj = (unsigned char *)malloc(obj_len);
    if (!obj) goto done;
    if (BCryptCreateHash(alg, &hash, obj, obj_len, NULL, 0, 0) != 0) { free(obj); goto done; }

    f = _wfopen(path, L"rb");
    if (!f) { BCryptDestroyHash(hash); free(obj); goto done; }

    unsigned long long total = file_size(path), done_bytes = 0;
    int last_pct = -1;
    unsigned char *buf = (unsigned char *)malloc(8 * 1024 * 1024);
    if (!buf) { fclose(f); BCryptDestroyHash(hash); free(obj); goto done; }
    size_t n;
    while ((n = fread(buf, 1, 8 * 1024 * 1024, f)) > 0) {
        if (BCryptHashData(hash, buf, (ULONG)n, 0) != 0) {
            free(buf); fclose(f); BCryptDestroyHash(hash); free(obj); goto done;
        }
        done_bytes += n;
        if (show_progress && total > 0) {
            int pct = (int)((done_bytes * 100ULL) / total);
            if (pct != last_pct && (pct % 5 == 0 || pct == 100)) {
                last_pct = pct;
                printf("\r    verifying... %d%%", pct);
                fflush(stdout);
            }
        }
    }
    free(buf);
    fclose(f);
    if (show_progress) printf("\n");
    if (BCryptFinishHash(hash, digest, sizeof(digest), 0) != 0) {
        BCryptDestroyHash(hash); free(obj); goto done;
    }
    BCryptDestroyHash(hash);
    free(obj);
    static const char *hexd = "0123456789abcdef";
    for (int i = 0; i < 32; i++) {
        out_hex[i * 2] = hexd[digest[i] >> 4];
        out_hex[i * 2 + 1] = hexd[digest[i] & 15];
    }
    out_hex[64] = '\0';
    rc = 0;
done:
    if (hash) { /* already destroyed on success path */ }
    if (alg) BCryptCloseAlgorithmProvider(alg, 0);
    return rc;
}

/* ---------- model copy with progress ---------- */

static DWORD CALLBACK copy_progress(LARGE_INTEGER total, LARGE_INTEGER done_bytes,
                                    LARGE_INTEGER stream_total, LARGE_INTEGER stream_done,
                                    DWORD stream_no, DWORD reason, HANDLE src, HANDLE dst,
                                    LPVOID data) {
    (void)stream_total; (void)stream_done; (void)stream_no; (void)reason;
    (void)src; (void)dst; (void)data;
    static int last_pct = -1;
    if (total.QuadPart > 0) {
        int pct = (int)((done_bytes.QuadPart * 100LL) / total.QuadPart);
        if (pct != last_pct) {
            last_pct = pct;
            printf("\r    copying model... %d%% (%.2f / %.2f GB)", pct,
                   done_bytes.QuadPart / 1073741824.0, total.QuadPart / 1073741824.0);
            fflush(stdout);
        }
    }
    return PROGRESS_CONTINUE;
}

/* ---------- main ---------- */

int main(void) {
    SetConsoleOutputCP(CP_UTF8);
    printf("============================================================\n");
    printf("  GENESIS Final - FULL Setup (app + brain model, offline)\n");
    printf("============================================================\n");

    /* own directory (the SFX extraction root) */
    wchar_t own[1024];
    DWORD on = GetModuleFileNameW(NULL, own, (DWORD)(sizeof(own) / sizeof(own[0])));
    if (on == 0) return fail("locate setup", "cannot resolve launcher path");
    wchar_t *slash = wcsrchr(own, L'\\');
    if (slash) *slash = L'\0';

    wchar_t setup_exe[1200], model_src[1200];
    path_join(setup_exe, 1200, own, L"setup\\GENESIS-Full-Setup.exe");
    path_join(model_src, 1200, own, L"payload\\" MODEL_NAME_W);
    if (!file_exists(setup_exe)) return fail("payload check", "app installer (setup\\GENESIS-Full-Setup.exe) missing from package");
    if (!file_exists(model_src) || file_size(model_src) != MODEL_SIZE_BYTES)
        return fail("payload check", "brain model payload missing or wrong size in package");

    wchar_t local_app[1024], pf[1024], pf86[1024];
    env_dir(L"LOCALAPPDATA", local_app, 1024);
    env_dir(L"ProgramFiles", pf, 1024);
    env_dir(L"ProgramFiles(x86)", pf86, 1024);
    if (!local_app[0]) return fail("paths", "LOCALAPPDATA not set");

    wchar_t inst_a[1200], inst_b[1200], inst_c[1200];
    path_join(inst_a, 1200, local_app, L"GENESIS Final");
    path_join(inst_b, 1200, pf, L"GENESIS Final");
    path_join(inst_c, 1200, pf86, L"GENESIS Final");

    printf("[1/5] Closing any running GENESIS...\n");
    kill_genesis_processes(inst_a);
    kill_genesis_processes(inst_b);
    Sleep(800);

    printf("[2/5] Installing the GENESIS app (silent)...\n");
    (void)run_and_wait(setup_exe, L"/S");
    wchar_t app_exe[1200];
    app_exe[0] = L'\0';
    for (int i = 0; i < 90 && !app_exe[0]; i++) {
        if (find_app_exe_in(inst_a, app_exe, 1200)) break;
        if (find_app_exe_in(inst_b, app_exe, 1200)) break;
        if (find_app_exe_in(inst_c, app_exe, 1200)) break;
        app_exe[0] = L'\0';
        Sleep(2000);
    }
    if (!app_exe[0]) return fail("app install", "GENESIS app executable not found after install");
    printf("    app installed.\n");

    printf("[3/5] Placing the brain model (5.85 GB)...\n");
    wchar_t data_dir[1200], models_dir[1200], model_dst[1400];
    path_join(data_dir, 1200, local_app, L"com.genesis.final");
    path_join(models_dir, 1200, data_dir, L"models");
    path_join(model_dst, 1400, models_dir, MODEL_NAME_W);
    CreateDirectoryW(data_dir, NULL);
    CreateDirectoryW(models_dir, NULL);

    int need_copy = 1;
    if (file_exists(model_dst) && file_size(model_dst) == MODEL_SIZE_BYTES) {
        char hex[65];
        printf("    existing model found - verifying before reuse...\n");
        if (sha256_hex(model_dst, hex, sizeof(hex), 1) == 0 &&
            strcmp(hex, MODEL_SHA256_HEX) == 0) {
            need_copy = 0;
            printf("    existing model verified OK - copy skipped.\n");
        } else {
            DeleteFileW(model_dst);
        }
    }
    if (need_copy) {
        BOOL cancel = FALSE;
        if (!CopyFileExW(model_src, model_dst, copy_progress, NULL, &cancel, 0)) {
            char msg[128];
            _snprintf(msg, sizeof(msg), "CopyFileEx failed (GetLastError=%lu)", GetLastError());
            return fail("model copy", msg);
        }
        printf("\n    model copied.\n");
    }

    printf("[4/5] Verifying the brain model (SHA-256 pin)...\n");
    {
        char hex[65];
        if (sha256_hex(model_dst, hex, sizeof(hex), 1) != 0)
            return fail("model verify", "could not hash the copied model");
        if (strcmp(hex, MODEL_SHA256_HEX) != 0) {
            DeleteFileW(model_dst);
            return fail("model verify", "SHA-256 mismatch - model deleted, rerun the setup");
        }
    }
    printf("    model verified OK.\n");

    printf("[5/5] Starting GENESIS...\n");
    {
        STARTUPINFOW si;
        PROCESS_INFORMATION pi;
        ZeroMemory(&si, sizeof(si));
        si.cb = sizeof(si);
        ZeroMemory(&pi, sizeof(pi));
        wchar_t dir[1200];
        wcsncpy(dir, app_exe, 1199);
        dir[1199] = L'\0';
        wchar_t *s2 = wcsrchr(dir, L'\\');
        if (s2) *s2 = L'\0';
        if (!CreateProcessW(app_exe, NULL, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi))
            return fail("launch", "installed app could not be started");
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
    printf("\nDone. GENESIS is fully installed - no downloads needed.\n");
    Sleep(3000);
    return 0;
}
