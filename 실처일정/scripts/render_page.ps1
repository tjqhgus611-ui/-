# Open an HWPX in Hangul (COM) and save page 1 as an image (verification only).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File render_page.ps1 <hwpx> <bmp>
# Hangul COM Open fails intermittently (RPC_E_SERVERFAULT, about half the time on this PC),
# so retry up to 4 times with a fresh COM object. A broken file never opens.
param([string]$src, [string]$img)
for ($i = 1; $i -le 4; $i++) {
    $hwp = $null
    try {
        $hwp = New-Object -ComObject HWPFrame.HwpObject
        try { $null = $hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule") } catch {}
        $ok = $hwp.Open($src, "HWPX", "forceopen:true;lock:false")
        if ($ok) {
            "open=True attempt=$i"
            "pages=" + $hwp.PageCount
            $null = $hwp.Run("Cancel")
            $null = $hwp.Run("MoveDocBegin")
            "img=" + $hwp.CreatePageImage($img, 0, 110, 24, "bmp")
            $hwp.Clear(1)
            $hwp.Quit()
            exit 0
        }
        "attempt=$i open returned false"
    } catch {
        "attempt=$i error: " + $_.Exception.Message
    }
    try { if ($hwp) { $hwp.Quit() } } catch {}
    Start-Sleep -Seconds 2
}
"open=False after 4 attempts"
exit 1
