#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <limits.h>

#ifndef CMDC_PROJECT_DIR
#error "CMDC_PROJECT_DIR must be set at build time"
#endif
#ifndef CMDC_VENV_DIR
#error "CMDC_VENV_DIR must be set at build time"
#endif
#ifndef CMDC_PYTHON_HOME
#error "CMDC_PYTHON_HOME must be set at build time"
#endif
#ifndef CMDC_PYTHON_DYLIB
#error "CMDC_PYTHON_DYLIB must be set at build time"
#endif
#ifndef CMDC_SITE_PACKAGES
#error "CMDC_SITE_PACKAGES must be set at build time"
#endif
#ifndef CMDC_STDLIB
#error "CMDC_STDLIB must be set at build time"
#endif

typedef int (*Py_BytesMain_t)(int, char **);

int main(int argc, char *argv[]) {
    // Project root and virtualenv paths
    const char *project_dir = CMDC_PROJECT_DIR;
    const char *venv_dir = CMDC_VENV_DIR;
    const char *python_home = CMDC_PYTHON_HOME;
    const char *dylib_path = CMDC_PYTHON_DYLIB;

    // Set up environment
    setenv("VIRTUAL_ENV", venv_dir, 1);
    setenv("PYTHONHOME", python_home, 1);

    char python_path[4096];
    snprintf(python_path, sizeof(python_path),
             "%s:%s:%s", CMDC_SITE_PACKAGES, project_dir, CMDC_STDLIB);
    setenv("PYTHONPATH", python_path, 1);

    const char *orig_path = getenv("PATH");
    char new_path[4096];
    snprintf(new_path, sizeof(new_path),
             "/Users/gw/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:%s",
             orig_path ? orig_path : "");
    setenv("PATH", new_path, 1);

    void *handle = dlopen(dylib_path, RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        fprintf(stderr, "cmdc: failed to load Python runtime (%s): %s\n", dylib_path, dlerror());
        return 1;
    }

    Py_BytesMain_t py_bytes_main = (Py_BytesMain_t)dlsym(handle, "Py_BytesMain");
    if (!py_bytes_main) {
        py_bytes_main = (Py_BytesMain_t)dlsym(handle, "Py_Main");
    }
    if (!py_bytes_main) {
        fprintf(stderr, "cmdc: failed to find Py_BytesMain in Python runtime: %s\n", dlerror());
        return 1;
    }

    char *py_argv[] = {
        argv[0],
        "-m",
        "cmdc.app",
        NULL
    };

    return py_bytes_main(3, py_argv);
}
