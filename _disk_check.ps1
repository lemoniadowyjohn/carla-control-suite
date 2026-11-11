$ErrorActionPreference = 'Continue'
foreach ($d in @('C','E','F','G','H')) {
    $f = Get-PSDrive $d -ErrorAction SilentlyContinue
    if ($f) {
        $freeGiB = [math]::Round($f.Free / 1GB, 2)
        $sizeGiB = [math]::Round($f.Size / 1GB, 2)
        Write-Output ("{0}: {1} GiB free / {2} GiB size" -f $d, $freeGiB, $sizeGiB)
    } else {
        Write-Output ("{0}: NOT MOUNTED" -f $d)
    }
}
