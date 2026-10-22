/*
 * GENESIS Complete 1.0.0 — BOOTSTRAPPER (native Win32, no dependencies
 * beyond the embedded official 7-Zip engine).
 *
 * Why this exists (2026-10-22, GENESIS ruling after complete-verify runs
 * 39665797415 / 39678558530 / 39764072162): the single-file 6.03 GB SFX
 * setup cannot be launched by the Windows loader (Win32 error 193 class,
 * "not a valid application for this OS platform") even though its bytes
 * are sha256-verified end-to-end and its PE machine is 0x8664. Every
 * GENESIS executable under 4 GiB launches fine. The distribution is
 * therefore split:
 *
 *   GENESIS.Complete_1.0.0_x64-bootstrapper.exe   (this file, ~2.6 MB)
 *   GENESIS.Complete_1.0.0_x64-setup.exe.part-00..03   (payload parts)
 *
 * The user downloads all five files into ONE folder and runs the
 * bootstrapper. It then, with VISIBLE PROGRESS at every phase:
 *
 *   [1/5] checks the 4 part files are present with their exact sizes,
 *   [2/5] joins them into GENESIS.Complete_1.0.0_x64-setup.exe,
 *   [3/5] verifies the joined bytes against the SHA-256 pin (BCrypt)
 *         — FAILS CLOSED and deletes the joined file on mismatch,
 *   [4/5] extracts the payload from the joined file (it is a 7z archive
 *         wrapped in an SFX stub; the embedded official 7-Zip x64 engine
 *         opens it directly) and size-checks every extracted entry,
 *   [5/5] runs the payload's own entry point, full-launcher.exe — which
 *         installs GENESIS-Full-Setup.exe, places + verifies the brain
 *         model, and launches GENESIS — and propagates its exit code.
 *
 * The payload bytes are the verified GENESIS Complete 1.0.0 payload,
 * reused exactly (never repacked): setup/GENESIS-Full-Setup.exe,
 * payload/genesis_369_v1_Q5_K_M.gguf, full-launcher.exe.
 *
 * Build (cross, on the build VM):
 *   python3 gen_engine_blobs.py engine/7z.exe engine/7z.dll engine_blobs.h
 *   zig cc -target x86_64-windows-gnu -O2 -s \
 *       -o GENESIS.Complete_1.0.0_x64-bootstrapper.exe bootstrapper.c -lbcrypt
 */

#include <windows.h>
#include <bcrypt.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

#include "engine_blobs.h"

/* ---------- distribution pins (fail-closed) ---------- */

#define JOINED_NAME_W   L"GENESIS.Complete_1.0.0_x64-setup.exe"
#define JOINED_SIZE     6030882143ULL
#define JOINED_SHA256   "27164113c5971391707e48b632864d0b5e51eefd3c3beb0fe9cdf1febcef8dc2"
#define PART_COUNT      4
static const unsigned long long PART_SIZES[PART_COUNT] = {
    1572864000ULL, 1572864000ULL, 1572864000ULL, 1312290143ULL
};
static const wchar_t *PART_NAMES[PART_COUNT] = {
    L"GENESIS.Complete_1.0.0_x64-setup.exe.part-00",
    L"GENESIS.Complete_1.0.0_x64-setup.exe.part-01",
    L"GENESIS.Complete_1.0.0_x64-setup.exe.part-02",
    L"GENESIS.Complete_1.0.0_x64-setup.exe.part-03"
};

/* extracted payload entry pins (sizes; full-launcher re-verifies the
   model SHA-256 itself before anything is installed from it) */
#define SETUP_EXE_SIZE    179679674ULL
#define MODEL_SIZE_BYTES  5851112800ULL
#define LAUNCHER_SIZE     43520ULL

#define WORK_DIR_W      L"genesis_complete_work"
#define EXTRACT_DIR_W   L"GENESIS.Complete_1.0.0_extracted"

static int fail(const char *step, const char *detail) {
    printf("\nERROR at step [%s]: %s\n", step, detail);
    printf("Nothing was hidden - report this message. Press Enter to close.\n");
    fflush(stdout);
    (void)getchar();
    return 1;
}

/* ---------- helpers (same proven shapes as full-launcher.c) ---------- */

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

/* Run a child with our console inherited (its progress stays visible),
   wait for it, return its exit code (-1 on launch failure). */
static int run_and_wait_inherit(const wchar_t *exe, const wchar_t *args, const wchar_t *cwd) {
    wchar_t cmd[4096];
    _snwprintf(cmd, sizeof(cmd) / sizeof(cmd[0]), L"\"%s\" %s", exe, args);
    cmd[(sizeof(cmd) / sizeof(cmd[0])) - 1] = L'\0';
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessW(NULL, cmd, NULL, NULL, TRUE, 0, NULL, cwd, &si, &pi))
        return -1;
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return (int)code;
}

/* ---------- SHA-256 (BCrypt) with progress ---------- */

static int sha256_hex(const wchar_t *path, char *out_hex, size_t out_cap) {
    if (out_cap < 65) return -1;
    BCRYPT_ALG_HANDLE alg = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    DWORD obj_len = 0, ret = 0;
    unsigned char digest[32];
    unsigned char *obj = NULL;
    FILE *f = NULL;
    int rc = -1;

    if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, 0) != 0) goto done;
    if (BCryptGetProperty(alg, BCRYPT_OBJECT_LENGTH, (PUCHAR)&obj_len, sizeof(obj_len), &ret, 0) != 0) goto done;
    obj = (unsigned char *)malloc(obj_len);
    if (!obj) goto done;
    if (BCryptCreateHash(alg, &hash, obj, obj_len, NULL, 0, 0) != 0) goto done;

    f = _wfopen(path, L"rb");
    if (!f) goto done;

    unsigned long long total = file_size(path), done_bytes = 0;
    int last_pct = -1;
    unsigned char *buf = (unsigned char *)malloc(8 * 1024 * 1024);
    if (!buf) goto done;
    size_t n;
    rc = 0;
    while ((n = fread(buf, 1, 8 * 1024 * 1024, f)) > 0) {
        if (BCryptHashData(hash, buf, (ULONG)n, 0) != 0) { rc = -1; break; }
        done_bytes += n;
        if (total > 0) {
            int pct = (int)((done_bytes * 100ULL) / total);
            if (pct != last_pct && (pct % 5 == 0 || pct == 100)) {
                last_pct = pct;
                printf("\r    verifying joined file... %d%%", pct);
                fflush(stdout);
            }
        }
    }
    free(buf);
    printf("\n");
    if (rc == 0 && BCryptFinishHash(hash, digest, sizeof(digest), 0) != 0) rc = -1;
    if (rc == 0) {
        static const char *hexd = "0123456789abcdef";
        for (int i = 0; i < 32; i++) {
            out_hex[i * 2] = hexd[digest[i] >> 4];
            out_hex[i * 2 + 1] = hexd[digest[i] & 15];
        }
        out_hex[64] = '\0';
    }
done:
    if (f) fclose(f);
    if (hash) BCryptDestroyHash(hash);
    if (obj) free(obj);
    if (alg) BCryptCloseAlgorithmProvider(alg, 0);
    return rc;
}

/* ---------- join with progress ---------- */

static int join_parts(const wchar_t *dir, const wchar_t *joined_path) {
    wchar_t tmp_path[1400];
    _snwprintf(tmp_path, sizeof(tmp_path) / sizeof(tmp_path[0]), L"%s.joining", joined_path);
    tmp_path[(sizeof(tmp_path) / sizeof(tmp_path[0])) - 1] = L'\0';

    HANDLE out = CreateFileW(tmp_path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                             FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    if (out == INVALID_HANDLE_VALUE) return -1;

    unsigned char *buf = (unsigned char *)malloc(8 * 1024 * 1024);
    if (!buf) { CloseHandle(out); DeleteFileW(tmp_path); return -1; }

    unsigned long long copied = 0;
    int last_pct = -1;
    int ok = 1;
    for (int i = 0; i < PART_COUNT && ok; i++) {
        wchar_t part[1400];
        path_join(part, 1400, dir, PART_NAMES[i]);
        HANDLE in = CreateFileW(part, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, NULL);
        if (in == INVALID_HANDLE_VALUE) { ok = 0; break; }
        for (;;) {
            DWORD rd = 0;
            if (!ReadFile(in, buf, 8 * 1024 * 1024, &rd, NULL)) { ok = 0; break; }
            if (rd == 0) break;
            DWORD wr_off = 0;
            while (wr_off < rd) {
                DWORD wr = 0;
                if (!WriteFile(out, buf + wr_off, rd - wr_off, &wr, NULL) || wr == 0) { ok = 0; break; }
                wr_off += wr;
            }
            if (!ok) break;
            copied += rd;
            int pct = (int)((copied * 100ULL) / JOINED_SIZE);
            if (pct != last_pct && (pct % 5 == 0 || pct == 100)) {
                last_pct = pct;
                printf("\r    joining parts... %d%% (%.2f / %.2f GB)", pct,
                       copied / 1073741824.0, JOINED_SIZE / 1073741824.0);
                fflush(stdout);
            }
        }
        CloseHandle(in);
    }
    free(buf);
    if (ok && !FlushFileBuffers(out)) ok = 0;
    CloseHandle(out);
    printf("\n");
    if (!ok || copied != JOINED_SIZE) { DeleteFileW(tmp_path); return -1; }
    DeleteFileW(joined_path);
    if (!MoveFileW(tmp_path, joined_path)) { DeleteFileW(tmp_path); return -1; }
    return 0;
}

/* ---------- embedded engine ---------- */

static int write_blob(const wchar_t *path, const unsigned char *data, size_t len) {
    FILE *f = _wfopen(path, L"wb");
    if (!f) return -1;
    size_t w = fwrite(data, 1, len, f);
    int c = fclose(f);
    return (w == len && c == 0) ? 0 : -1;
}

/* ---------- main ---------- */

int main(void) {
    SetConsoleOutputCP(CP_UTF8);
    printf("============================================================\n");
    printf("  GENESIS Complete 1.0.0 - Bootstrapper\n");
    printf("  Joins the 4 setup parts, verifies them, installs GENESIS.\n");
    printf("============================================================\n");

    /* own directory = the folder the user put the parts in */
    wchar_t own[1024];
    DWORD on = GetModuleFileNameW(NULL, own, (DWORD)(sizeof(own) / sizeof(own[0])));
    if (on == 0) return fail("locate bootstrapper", "cannot resolve own path");
    wchar_t *slash = wcsrchr(own, L'\\');
    if (slash) *slash = L'\0';

    /* [1/5] parts present, exact sizes */
    printf("[1/5] Checking the 4 setup parts...\n");
    for (int i = 0; i < PART_COUNT; i++) {
        wchar_t part[1400];
        path_join(part, 1400, own, PART_NAMES[i]);
        if (!file_exists(part)) {
            char msg[512];
            _snprintf(msg, sizeof(msg),
                      "missing file: GENESIS.Complete_1.0.0_x64-setup.exe.part-0%d - "
                      "download ALL 5 files (bootstrapper + 4 parts) into ONE folder and run again", i);
            return fail("parts check", msg);
        }
        unsigned long long sz = file_size(part);
        if (sz != PART_SIZES[i]) {
            char msg[256];
            _snprintf(msg, sizeof(msg),
                      "part-0%d has the wrong size (%llu bytes, expected %llu) - the download is incomplete or corrupted",
                      i, sz, PART_SIZES[i]);
            return fail("parts check", msg);
        }
    }
    printf("    all 4 parts present, sizes exact.\n");

    /* free-space guard: joined (6.03 GB) + extracted payload (6.03 GB) */
    {
        ULARGE_INTEGER freeb;
        if (GetDiskFreeSpaceExW(own, &freeb, NULL, NULL)) {
            unsigned long long need = JOINED_SIZE + 6030835994ULL + 268435456ULL;
            wchar_t joined_path[1400];
            path_join(joined_path, 1400, own, JOINED_NAME_W);
            if (file_exists(joined_path) && file_size(joined_path) == JOINED_SIZE)
                need -= JOINED_SIZE;
            if (freeb.QuadPart < need) {
                char msg[256];
                _snprintf(msg, sizeof(msg),
                          "not enough free disk space here (%.1f GB free, %.1f GB needed)",
                          freeb.QuadPart / 1073741824.0, need / 1073741824.0);
                return fail("disk space", msg);
            }
        }
    }

    /* [2/5] join */
    wchar_t joined_path[1400];
    path_join(joined_path, 1400, own, JOINED_NAME_W);
    printf("[2/5] Joining parts into the complete setup file...\n");
    if (file_exists(joined_path) && file_size(joined_path) == JOINED_SIZE) {
        printf("    joined file already present (size exact) - skipping join.\n");
    } else {
        if (join_parts(own, joined_path) != 0)
            return fail("join", "could not join the parts (see message above)");
        printf("    joined: %llu bytes.\n", JOINED_SIZE);
    }

    /* [3/5] verify joined bytes against the pin — fail closed */
    printf("[3/5] Verifying the joined file (SHA-256 pin)...\n");
    {
        char hex[65];
        if (sha256_hex(joined_path, hex, sizeof(hex)) != 0)
            return fail("verify", "could not hash the joined file");
        if (strcmp(hex, JOINED_SHA256) != 0) {
            DeleteFileW(joined_path);
            return fail("verify",
                        "SHA-256 mismatch - the joined file was DELETED. "
                        "Re-download the parts and run again");
        }
    }
    printf("    joined file verified OK (sha256 = release pin).\n");

    /* [4/5] extract payload with the embedded official 7-Zip engine */
    printf("[4/5] Extracting the setup payload...\n");
    wchar_t work_dir[1400], engine_dir[1400], extract_dir[1400];
    path_join(work_dir, 1400, own, WORK_DIR_W);
    path_join(engine_dir, 1400, work_dir, L"engine");
    path_join(extract_dir, 1400, own, EXTRACT_DIR_W);
    CreateDirectoryW(work_dir, NULL);
    CreateDirectoryW(engine_dir, NULL);
    CreateDirectoryW(extract_dir, NULL);

    wchar_t seven_exe[1400], seven_dll[1400];
    path_join(seven_exe, 1400, engine_dir, L"7z.exe");
    path_join(seven_dll, 1400, engine_dir, L"7z.dll");
    if (write_blob(seven_exe, k7zExe, k7zExeLen) != 0 ||
        write_blob(seven_dll, k7zDll, k7zDllLen) != 0)
        return fail("extract", "could not stage the embedded 7-Zip engine");
    if (file_size(seven_exe) != (unsigned long long)k7zExeLen ||
        file_size(seven_dll) != (unsigned long long)k7zDllLen)
        return fail("extract", "embedded 7-Zip engine staged with wrong size");

    {
        wchar_t args[3000];
        _snwprintf(args, sizeof(args) / sizeof(args[0]),
                   L"x -y -bsp1 -o\"%s\" \"%s\"", extract_dir, joined_path);
        args[(sizeof(args) / sizeof(args[0])) - 1] = L'\0';
        int rc = run_and_wait_inherit(seven_exe, args, work_dir);
        if (rc != 0) {
            char msg[128];
            _snprintf(msg, sizeof(msg), "7-Zip extraction failed (exit code %d)", rc);
            return fail("extract", msg);
        }
    }
    /* size-check every extracted entry — fail closed */
    {
        wchar_t p[1600];
        path_join(p, 1600, extract_dir, L"setup\\GENESIS-Full-Setup.exe");
        if (!file_exists(p) || file_size(p) != SETUP_EXE_SIZE)
            return fail("extract", "payload incomplete: setup\\GENESIS-Full-Setup.exe missing or wrong size");
        path_join(p, 1600, extract_dir, L"payload\\genesis_369_v1_Q5_K_M.gguf");
        if (!file_exists(p) || file_size(p) != MODEL_SIZE_BYTES)
            return fail("extract", "payload incomplete: the brain model is missing or wrong size");
        path_join(p, 1600, extract_dir, L"full-launcher.exe");
        if (!file_exists(p) || file_size(p) != LAUNCHER_SIZE)
            return fail("extract", "payload incomplete: full-launcher.exe missing or wrong size");
    }
    printf("    payload extracted and size-verified.\n");

    /* [5/5] run the payload's entry point; it installs the app, places
       and sha-verifies the model, launches GENESIS. Propagate its code. */
    printf("[5/5] Running the GENESIS setup (install + brain model)...\n");
    wchar_t launcher[1400];
    path_join(launcher, 1400, extract_dir, L"full-launcher.exe");
    int rc = run_and_wait_inherit(launcher, L"", extract_dir);
    if (rc < 0) return fail("setup", "the payload launcher could not be started");
    if (rc != 0) {
        char msg[128];
        _snprintf(msg, sizeof(msg), "the setup reported a problem (exit code %d) - see its message above", rc);
        return fail("setup", msg);
    }
    printf("\nDone. GENESIS Complete 1.0.0 is installed.\n");
    Sleep(3000);
    return 0;
}
