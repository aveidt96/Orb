param([string]$Voice)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$script = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'narration.json') -Raw | ConvertFrom-Json
$work = Join-Path $PSScriptRoot '../../output/orb-product-demo/work/voiceover'
if (-not (Test-Path -LiteralPath (Split-Path $work -Parent))) { throw 'Video work directory is missing.' }
[System.IO.Directory]::CreateDirectory($work) | Out-Null
$speaker = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $speaker.SelectVoice($(if ($Voice) { $Voice } else { $script.voice }))
    $speaker.Rate = $script.rate
    $speaker.Volume = 100
    foreach ($cue in $script.cues) {
        $spoken = $cue.text.Replace('OpenCV', 'Open C V').Replace('Orb AI', 'Orb A I').Replace('AWS', 'A W S')
        $speaker.SetOutputToWaveFile((Join-Path $work ($cue.id + '.wav')))
        $speaker.Speak($spoken)
        $speaker.SetOutputToNull()
        "Synthesized $($cue.id)"
    }
    @{voice=$speaker.Voice.Name; language=$speaker.Voice.Culture.Name; rate=$speaker.Rate; engine='Windows System.Speech offline synthesis'} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $work 'voice.json') -Encoding utf8
} finally {
    $speaker.Dispose()
}
