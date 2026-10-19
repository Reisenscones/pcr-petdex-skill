param(
    [Parameter(Mandatory)][string]$ModelPath,
    [Parameter(Mandatory)][string]$LibraryDirectory,
    [Parameter(Mandatory)][string]$OutputPath,
    [string]$Animation = '000000_balloon_flying_loop',
    [string]$Slot = 'handB',
    [int]$FrameCount = 40,
    [double]$Fps = 30,
    [int]$WindowSize = 640,
    [double]$CenterX = -225,
    [double]$CenterY = 625,
    [double]$Scale = 0.4,
    [double]$PalmOffsetX = 24,
    [double]$PalmOffsetY = 7.5
)

$ErrorActionPreference = 'Stop'
[System.Reflection.Assembly]::LoadFrom((Join-Path $LibraryDirectory 'Spine.dll')) | Out-Null
Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
public static class SpineAnchorNative {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)]
    public static extern bool SetDllDirectory(string path);
}
'@
[SpineAnchorNative]::SetDllDirectory($LibraryDirectory) | Out-Null
$spine = [Spine.SpineObject]::new($ModelPath, '', $null, $null)
try {
    $spine.AnimationState.SetAnimation(0, $Animation, $true) | Out-Null
    $spine.Update(0)
    $frames = for ($i = 0; $i -lt $FrameCount; $i++) {
        $hand = $spine.Skeleton.SlotsByName[$Slot]
        $offset = $hand.Attachment.InnerObject.Offset
        if ($offset.Count -ne 8) { throw 'The hand must use a region attachment.' }
        # The hand texture also contains the wrist ornament. This calibrated
        # offset moves its centre onto the palm in the hand's local axes.
        $localX = ($offset[0]+$offset[2]+$offset[4]+$offset[6])/4 + $PalmOffsetX
        $localY = ($offset[1]+$offset[3]+$offset[5]+$offset[7])/4 + $PalmOffsetY
        $bone = $hand.Bone
        $worldX = $bone.WorldX + $bone.A*$localX + $bone.B*$localY
        $worldY = $bone.WorldY + $bone.C*$localX + $bone.D*$localY
        @{
            index = $i
            point = @(
                [math]::Round($WindowSize/2+($worldX-$CenterX)*$Scale, 4),
                [math]::Round($WindowSize/2+($CenterY-$worldY)*$Scale, 4)
            )
        }
        $spine.Update([single](1.0/$Fps))
    }
    @{
        format_version = 1
        animation = $Animation
        slot = $Slot
        fps = $Fps
        frames = @($frames)
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding utf8NoBOM
} finally {
    $spine.Dispose()
}
