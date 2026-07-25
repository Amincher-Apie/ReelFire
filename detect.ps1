# ReelFire Video Detection Tool
# Usage: .\detect.ps1 [options]
#
# Examples:
#   .\detect.ps1                          # Batch detect all videos in test_videos
#   .\detect.ps1 -Video test_01.mp4       # Detect single video
#   .\detect.ps1 -Conf 0.25               # Lower confidence threshold

param(
    [string]$Video,
    [string]$Model = "runs/detect/custom_fps_v5/weights/best.pt",
    [string]$Output = "outputs/video_detect_v5",
    [double]$Conf = 0.35
)

$env:KMP_DUPLICATE_LIB_OK = "TRUE"
$env:PYTHONIOENCODING = "utf-8"

if ($Video) {
    # Single video mode
    Write-Host "Detecting: $Video" -ForegroundColor Cyan
    python -m cv_engine.video_detector --video "test_videos/$Video" --model $Model --output $Output --conf $Conf
} else {
    # Batch mode
    $files = Get-ChildItem "test_videos" -Filter "*.mp4"
    if ($files.Count -eq 0) {
        Write-Host "No videos found in test_videos/" -ForegroundColor Red
        exit 1
    }
    Write-Host "Found $($files.Count) video(s) in test_videos/" -ForegroundColor Cyan
    foreach ($f in $files) {
        Write-Host "`n--- Detecting: $($f.Name) ---" -ForegroundColor Yellow
        python -m cv_engine.video_detector --video $f.FullName --model $Model --output $Output --conf $Conf
    }
    Write-Host "`nAll done! Results in: $Output" -ForegroundColor Green
}
