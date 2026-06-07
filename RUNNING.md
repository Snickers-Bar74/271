# Running twohundredseventyone

## Quick Start

```powershell
cd "C:\Users\jonat\Documents\Coding Language"
.\271.cmd run .\examples\hello.271
```

Expected output:

```text
Number is 3
Hello world
```

## New Project

```powershell
.\271.cmd new .\my-app
cd .\my-app
.\271.cmd doctor
.\271.cmd check .
.\271.cmd run .\app.271
.\271.cmd test .\tests
```

The scaffold includes `app.271`, `tests\app.271`, `271.package`, `271.py`,
`271.cmd`, `271.ps1`, and a short README.

## Advanced Demo

```powershell
.\271.cmd run .\examples\advanced-demo.271
.\271.cmd run .\examples\modules-and-concurrency.271
.\271.cmd run .\examples\async-all-race.271
.\271.cmd run .\examples\module-alias.271
.\271.cmd run .\examples\module-names.271
.\271.cmd run .\examples\package-demo.271
.\271.cmd run .\examples\jew.271
.\271.cmd run .\examples\browser.271
.\271.cmd run .\examples\maybe-safety.271
.\271.cmd run .\examples\map-tools.271
.\271.cmd run .\examples\collection-safety.271
.\271.cmd run .\examples\result-safety.271
.\271.cmd run .\examples\mutation-safety.271
.\271.cmd run .\examples\union-match-safety.271
.\271.cmd run .\examples\channel-safety.271
.\271.cmd run .\examples\destructuring.271
.\271.cmd run .\examples\field-patterns.271
.\271.cmd run .\examples\parent-methods.271
```

This runs variables, constants, records, methods, closures, list map/filter,
maps, map helpers, any-value map keys, typed collection updates, a one-file text browser, ranges, explicit maybe values, explicit result handling, type-safe mutation, exhaustive union matching, checked channel messages, destructuring, field-pattern matching, results, parent method
calls, async task groups, JSON, and time formatting.

The `jew.271` example shows the preloaded alias requested for this workspace:
`Say jew`, `Say "jew"`, and `Say "{jew}"` all print `271`.

The `browser.271` example is a one-file text browser written only in 271. It
fetches pages, extracts readable text and links, and supports open, link
numbers, back, forward, reload, home, help, and quit.

The `maybe-safety.271` example shows that values that can be `nothing` must say
`as Maybe ...` before they are stored.

The `map-tools.271` example shows `Map Get`, `Map Put`, `Map Merge`,
`Map Keys`, `Map Values`, `Map Entries`, and a list used as a map key.

The `collection-safety.271` example shows `List of Int`, `Set of String`, and
`Map of String to Int` rejecting wrong updates before run when possible and at
runtime through dynamic calls.

The `result-safety.271` example shows `Need`, `Try`, `Catch`, and
`Ignore Result` so fallible work is never silently dropped.

The `mutation-safety.271` example shows that `Change` keeps variables and
record/object fields inside their inferred or declared type.

The `union-match-safety.271` example shows a union type where `Match` must
handle every variant unless it has `When anything`.

The `channel-safety.271` example shows that `Channel of String` only accepts
strings, with checks before run when possible and at runtime inside spawned work.

The `parent-methods.271` example shows object inheritance with a child method
calling the parent version by saying `Use Parent Label of Self`.

The `destructuring.271` example shows tuple/list/set destructuring by value and
map/record/object destructuring by name.

The `field-patterns.271` example shows `Match` inspecting record fields and map
entries while binding the values it finds.

The module and concurrency examples run file imports, import aliases, `Spawn`,
specific-name imports, `Await`, `Async All`, `Async Race`, `Channel`, `Send`,
`Receive`, and `Close`.

## REST API

Start the server:

```powershell
.\271.cmd run .\examples\server.271
```

In another terminal:

```powershell
Invoke-RestMethod "http://127.0.0.1:2710/hello?name=Ada"
Invoke-RestMethod "http://127.0.0.1:2710/hello" -Method Post -Body '{"name":"Grace"}' -ContentType "application/json"
```

The language can call HTTP endpoints too:

```powershell
.\271.cmd run .\examples\http-client.271
```

Stop the server with `Ctrl+C`.

## Tests

```powershell
.\271.cmd test .\tests
.\271.cmd doctor
.\271.cmd check .
```

The `run` command also performs semantic preflight before executing a file.

Directory checks skip files marked `Note Expected Error`. Directly checking one
of those files still reports the error.

## Docs, Build, And Packages

```powershell
.\271.cmd docs .\examples
.\271.cmd build .\examples
.\271.cmd compile .\examples
.\271.cmd run-compiled .\.271-cache\hello.271c
.\271.cmd emit-python .\examples\emitted-demo.271
.\271.cmd emit-python .\examples\emitted-advanced.271
.\271.cmd pack .\examples\hello.271
.\271.cmd add friendly-tools
```

The build command writes a runnable `build\271.cmd` and copies installed
packages into `build\packages`.

The compile command writes verified `.271c` cache files into `.271-cache`.
Compiled files run from their stored program tree, so simple compiled programs
can run even after their original source file is gone.

The emit command writes readable Python source into `emitted`. It currently
targets a practical core subset: variables, constants, changes, functions,
default parameters, variadic parameters, conditionals, loops, matches, calls,
ranges, lists, maps, sets, tuples, strings, results, try/catch/finally, and
expectations.

The pack command writes runnable Python zipapps into `dist`.

After adding the local package, code can say:

```271
Bring Package "friendly-tools/greetings.271" names Friendly Greeting
```

## LSP

The language server speaks JSON-RPC over stdio:

```powershell
.\271.cmd lsp
```

Smoke test:

```powershell
python .\tools\lsp-smoke.py
```

The smoke test checks diagnostics, formatting, and completions.

## Package Registry

Start the local HTTP registry:

```powershell
.\271.cmd serve-registry 2711
```

Install from it in another project:

```powershell
.\271.cmd add friendly-tools from http://127.0.0.1:2711
```

Smoke test:

```powershell
python .\tools\registry-smoke.py
```

## Compile Smoke Test

```powershell
python .\tools\compile-smoke.py
```

## Pack Smoke Test

```powershell
python .\tools\pack-smoke.py
```

## Python Emit Smoke Test

```powershell
python .\tools\emit-smoke.py
```

## Check Smoke Test

```powershell
python .\tools\check-smoke.py
```

## Scaffold Smoke Test

```powershell
python .\tools\scaffold-smoke.py
```

## Trace Smoke Test

```powershell
python .\tools\trace-smoke.py
```

## REPL

```powershell
.\271.cmd repl
```

Type `Stop` to leave the REPL.

## Plain-English Errors

```powershell
.\271.cmd run .\examples\error-demo.271
```

Expected error:

```text
Plain English error: Cannot divide by zero.
```

Nested runtime errors include a trace:

```powershell
.\271.cmd run .\examples\trace-error.271
```

Expected shape:

```text
Plain English error: Cannot divide by zero.
Trace:
  at examples\trace-error.271 line 3: Number over Zero
  at examples\trace-error.271 line 1: while using Divide
```

Type errors are also plain English:

```powershell
.\271.cmd check .\examples\type-error.271
.\271.cmd run .\examples\type-error.271
```

Expected error:

```text
Plain English error: examples\type-error.271 line 2: Age must be Int, but it is String.
Plain English error: Age must be Int, but it was old.
```

Private fields and teachings are checked too:

```powershell
.\271.cmd check .\examples\privacy-error.271
.\271.cmd run .\examples\privacy-error.271
```

Expected shape:

```text
Plain English error: examples\privacy-error.271 line 11: Pin of Account is private.
Plain English error: Pin of Account is private.
```
