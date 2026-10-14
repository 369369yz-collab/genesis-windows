# Chromium pin for GENESIS Full
# We do NOT vendor a random Chromium zip. The Python brain drives browsers
# through Playwright, so the pinned Playwright version decides the Chromium
# build. Single source of truth: requirements pin below.

playwright==1.49.1

# After `pip install playwright==1.49.1 && playwright install chromium`,
# the executable lives at (Windows):
#   %USERPROFILE%\AppData\Local\ms-playwright\chromium-<build>\chrome-win\chrome.exe
# fetch_chromium.py resolves and prints that exact path; the Tauri sidecar
# passes it to BrowserService as chromium_path.

# Headless is the default. Headed/live-view uses the same binary.
# Zero spend: Playwright + Chromium are free (Apache-2.0 / BSD).
