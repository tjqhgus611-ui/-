# Convert one HWP file to HWPX with Hangul COM (source file is not modified).
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File hwp_to_hwpx.ps1 <src.hwp> <dst.hwpx>
# Hangul COM fails intermittently on this PC, so retry up to 4 times.
param([string]$src, [string]$dst)
for ($i = 1; $i -le 4; $i++) {
    $hwp = $null
    try {
        $hwp = New-Object -ComObject HWPFrame.HwpObject
        try { $null = $hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule") } catch {}
        $ok = $hwp.Open($src, "HWP", "forceopen:true;lock:false")
        if ($ok) {
            $saved = $hwp.SaveAs($dst, "HWPX", "")
            $hwp.Clear(1)
            $hwp.Quit()
            if ($saved -and (Test-Path -LiteralPath $dst)) { "converted attempt=$i"; exit 0 }
            "attempt=$i saveas failed"
        } else { "attempt=$i open returned false" }
    } catch {
        "attempt=$i error: " + $_.Exception.Message
    }
    try { if ($hwp) { $hwp.Quit() } } catch {}
    Start-Sleep -Seconds 2
}
"failed after 4 attempts"
exit 1
