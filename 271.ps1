$Python = "C:\Users\jonat\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Runner = Join-Path $PSScriptRoot "271.py"
& $Python $Runner @args
exit $LASTEXITCODE
