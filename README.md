# twohundredseventyone

twohundredseventyone is a plain-English programming language. The syntax is
centered on sentence-shaped code:

```271
Make Number be 3
Say "Number is {Number}"
```

This folder now includes both the language design and a local runnable
interpreter.

## Run It

Open PowerShell or Command Prompt:

```powershell
cd "C:\Users\jonat\Documents\Coding Language"
.\271.cmd run .\examples\hello.271
```

PowerShell may block `271.ps1` because of your execution policy, so `271.cmd` is
the easiest launcher on this machine.

## Useful Commands

```powershell
.\271.cmd version
.\271.cmd doctor
.\271.cmd new .\my-app
.\271.cmd check .
.\271.cmd run .\examples\hello.271
.\271.cmd run .\examples\advanced-demo.271
.\271.cmd run .\examples\modules-and-concurrency.271
.\271.cmd run .\examples\async-all-race.271
.\271.cmd run .\examples\module-alias.271
.\271.cmd run .\examples\module-names.271
.\271.cmd run .\examples\package-demo.271
.\271.cmd run .\examples\jew.271
.\271.cmd run .\examples\maybe-safety.271
.\271.cmd run .\examples\collection-safety.271
.\271.cmd run .\examples\destructuring.271
.\271.cmd run .\examples\field-patterns.271
.\271.cmd run .\examples\parent-methods.271
.\271.cmd run .\examples\server.271
.\271.cmd test .\tests
.\271.cmd lint .\examples\server.271
.\271.cmd docs .\examples
.\271.cmd build .\examples
.\271.cmd compile .\examples
.\271.cmd emit-python .\examples\emitted-demo.271
.\271.cmd pack .\examples\hello.271
.\271.cmd add friendly-tools
.\271.cmd serve-registry 2711
.\271.cmd repl
.\271.cmd lsp
```

When the server is running:

```powershell
Invoke-RestMethod "http://127.0.0.1:2710/hello?name=Ada"
Invoke-RestMethod "http://127.0.0.1:2710/hello" -Method Post -Body '{"name":"Grace"}' -ContentType "application/json"
```

## What Is Included

- `271.py`: local interpreter and CLI
- `271.cmd`: Windows launcher that works despite PowerShell script policy
- `271.ps1`: PowerShell launcher for machines that allow local scripts
- `tools/scaffold-smoke.py`: creates and verifies a fresh project scaffold
- `tools/check-smoke.py`: semantic checker smoke test
- `tools/trace-smoke.py`: runtime trace smoke test
- `examples/hello.271`: smallest runnable example
- `examples/advanced-demo.271`: functions, closures, records, lists, maps, ranges, matches, JSON, and time
- `examples/modules-and-concurrency.271`: file modules, spawn, await, and channels
- `examples/async-all-race.271`: wait for many tasks or the first finished task
- `examples/module-alias.271`: namespaced module imports
- `examples/module-names.271`: importing specific names from a source file
- `examples/http-client.271`: HTTP GET and POST client calls against the local server
- `examples/package-demo.271`: installed local package import
- `examples/emitted-demo.271`: small program that can be emitted to standalone Python source
- `examples/emitted-advanced.271`: emitter coverage for maps, sets, matches, results, loops, defaults, variadics, and try/catch/finally
- `examples/jew.271`: preloaded alias example where `jew` says `271`
- `examples/maybe-safety.271`: explicit `Maybe` values and safe matching
- `examples/maybe-error.271`: expected-error demo for missing `Maybe` annotations
- `examples/map-tools.271`: map lookup, update, merge, entries, and non-string keys
- `examples/map-error.271`: expected-error demo for unchecked map lookup
- `examples/collection-safety.271`: typed collection updates for lists, sets, and maps
- `examples/collection-error.271`: expected-error demo for wrong typed collection items
- `examples/collection-runtime-error.271`: expected-runtime-error demo for typed collections through dynamic calls
- `examples/result-safety.271`: explicit `Result` handling and explicit result discard
- `examples/result-error.271`: expected-error demo for ignored `Result` values
- `examples/mutation-safety.271`: type-safe changes for variables and fields
- `examples/mutation-error.271`: expected-error demo for type-changing mutation
- `examples/union-match-safety.271`: exhaustive `Match` over a union type
- `examples/union-match-error.271`: expected-error demo for missing a union variant
- `examples/channel-safety.271`: typed channel send and receive
- `examples/channel-error.271`: expected-error demo for wrong channel message type
- `examples/channel-runtime-error.271`: expected-runtime-error demo for typed channels inside spawned work
- `examples/destructuring.271`: safe destructuring for tuples, lists, sets, maps, records, and objects
- `examples/destructure-error.271`: expected-error demo for bad destructuring
- `examples/field-patterns.271`: match records and maps by their fields
- `examples/field-pattern-error.271`: expected-error demo for bad field patterns
- `examples/parent-methods.271`: overriding methods, parent method calls, and subtype checks
- `examples/server.271`: working local REST API
- `examples/error-demo.271`: plain-English runtime error
- `examples/trace-error.271`: nested runtime error with a plain-English trace
- `examples/privacy-error.271`: expected-error demo for private fields and private teachings
- `examples/parent-error.271`: expected-error demo for bad parent method calls
- `examples/type-error.271`: expected-error demo that direct `check` and `run` both reject in plain English
- `examples/contract-error.271`: plain-English contract error
- `tests/`: runnable language tests
- `registry/`: local package registry
- `packages/`: installed packages
- `tools/lsp-smoke.py`: JSON-RPC LSP smoke test
- `tools/registry-smoke.py`: remote package registry smoke test
- `tools/compile-smoke.py`: compiled artifact smoke test
- `tools/emit-smoke.py`: Python source emitter smoke test
- `tools/pack-smoke.py`: packaged app smoke test
- `271.package` and `271.lock`: package manifest and lock file
- `twohundredseventyone-spec.md`: full language spec
- `cheat-sheet.md`: one-page syntax reference
- `comparison.md`: comparison with Python, JavaScript, and Go
- `hello-to-rest-api.md`: five-step guide

Generated folders such as `.271-cache`, `build`, `dist`, and `emitted`, plus
`271-docs.md`, are intentionally not kept in the clean project. They are
recreated when you run `compile`, `build`, `pack`, `emit-python`, or `docs`.

## Current Runner Support

The local runner supports:

- `Make`, `Keep`, destructuring with `and`, and type-safe `Change`
- expression-style `If` and `Match` assignments such as `Make Name be If Condition`
- optional type annotations that are checked at runtime and preflighted statically for obvious literal/container mismatches
- explicit `Maybe` annotations for values that can be `nothing`
- `Say`, `Ask`, and string interpolation
- `If`, `Otherwise if`, `Otherwise`
- `Match` with `Some`, `nothing`, `Success`, `Failure`, list patterns, map patterns, field patterns, type patterns, union exhaustiveness checks, and HTTP request patterns
- `Repeat for`, `Repeat while`, `Repeat forever`, `Stop`, and `Skip`
- `Teach`, anonymous teachings, closures, default parameters, and variadic parameters
- `Record`, `Object`, methods, generated constructors, single inheritance, parent method calls with `Use Parent`, and field access with `of`
- private fields and private teachings enforced by both `check` and runtime
- enforced `Contract` declarations for records and objects
- `Bring "file.271"`, `Bring "file.271" names Name`, and `Bring "file.271" as Name`
- `Bring Package "name/file.271"` after `.\271.cmd add name`
- `List`, `Map`, multi-line `Map with`, map keys of any language value, `Set`, `Tuple`, `Range`, safe item access, safe destructuring, and typed collection updates
- `Result`, `Success`, `Failure`, `Need`, `Ignore Result`, `Try`, `Catch`, and `Finally`
- plain-English runtime traces for nested failures in teachings, compiled programs, and packaged apps
- preloaded alias `jew`, where `Say jew` and `Say "jew"` both print `271`
- `Spawn`, `Await`, `Async All`, `Async Race`, typed `Channel`, checked `Send`, `Receive`, and `Close`
- built-in `String`, `List`, `Map`, `Math`, `File`, `Json`, `Time`, `OS`, `Regex`, `Async`, `Http Get`, `Http Post`, and `Http Serve`
- local `new`, `doctor`, `check`, `run`, `run-compiled`, `repl`, `test`, `lint`, `format`, `docs`, `add`, `build`, `compile`, `emit-python`, `pack`, `serve-registry`, `lsp`, and `version` commands
- semantic preflight checks during `check` and `run` for unknown names, ignored `Result` values, wrong channel message types, wrong typed collection items, missing union `Match` branches, type-changing mutation, bad call targets, method argument types, parent-call misuse, missing `Maybe` annotations including unchecked map lookups, bad destructuring, bad field patterns, kept-value changes, missing imports, misplaced `Stop`/`Skip`, malformed maps, and clear type mismatches
- fresh project scaffolding with app, tests, package manifest, launchers, and copied runner
- toolchain health checks through `doctor`
- a real stdio LSP server with diagnostics and formatting
- LSP keyword completions for the plain-English syntax
- a local HTTP package registry server and remote install support
- a compiled `.271c` AST/cache backend that runs without the original source
- a readable Python source emitter for variables, functions, defaults, variadics, loops, matches, maps, sets, tuples, results, try/catch/finally, and a practical core subset
- packaged Python zipapps that run compiled program trees without source files

The design spec is more ambitious than this first interpreter, but the runner
is now a working foundation with real modules, type checks, contracts,
concurrency, HTTP client/server support, project scaffolding, semantic
preflight checks, toolchain doctor checks, a local package registry, a real LSP
server, remote package install, compile cache artifacts, emitted Python source,
map utilities with any-value keys, typed collection update safety, ignored-Result protection, exhaustive union matches, checked channel messages, type-safe mutation, tests, docs, self-contained runnable build output, packaged apps, and a REST
server example.
