# twohundredseventyone vs Python vs JavaScript vs Go

| Topic | twohundredseventyone | Python | JavaScript | Go |
| --- | --- | --- | --- | --- |
| Main design goal | Readable aloud, one English spelling per concept, explicit failure | Readability and batteries included | Web ubiquity and flexible runtime behavior | Simple compiled systems and services language |
| Blocks | Exactly 2-space indentation | Indentation | Braces | Braces |
| Line endings | No punctuation | No punctuation | Semicolons optional | No semicolons written by users in normal code |
| Variables | `Make Number be 3` | `number = 3` | `let`, `const`, `var` | `var`, `:=`, typed declarations |
| Constants | `Keep Max Retries be 3` | Convention only | `const`, not visually enforced | `const` |
| Reassignment | `Change Number to Number plus 1`, checked against the original type | Assignment expression | Assignment expression | Assignment statement |
| Type annotations | Optional, inferred by default | Optional through typing module | Optional only with TypeScript, not JavaScript | Often required or inferred with `:=` |
| Null or absence | `nothing`, values that may be absent must use explicit `Maybe` | `None`, allowed broadly | `null` and `undefined` | `nil` for some types |
| Truthiness | None, conditions must be `Bool` | Many truthy/falsy values | Many truthy/falsy values | Conditions must be `bool` |
| Functions | `Teach Add using Left and Right` | `def`, `lambda` | `function`, arrows, methods | `func` |
| Anonymous functions | `Teach using Number give Number times 2` | `lambda x: x + 1` | `x => x + 1` | Function literal |
| Calls | `Use Add with 2 and 3` | `add(2, 3)` | `add(2, 3)` | `add(2, 3)` |
| Return | Last value by default, no return keyword | `return` required for values | `return` required for values | `return` required for values |
| Loops | One `Repeat` construct for all loop shapes | `for` and `while` | `for`, `while`, `do while`, iterators | `for` only, with several forms |
| Pattern matching | `Match` over values, types, maybe values, lists, maps, records, objects, and exhaustive unions | `match` in modern Python | `switch`, no full built-in pattern matching | `switch`, type switches |
| Lists or arrays | `List with 1 and 2 and 3`, dynamic and mixed values allowed | Dynamic lists | Dynamic arrays | Arrays and slices, typed |
| Maps | `Map with "Ada" meaning 10`, any language value can be a key | Dict, hashable keys | Object and Map | Map, comparable keys |
| Sets | `Set with "work" and "urgent"` | Built-in set | Set | No built-in set type |
| Tuples | `Tuple with 10 and 20`, fixed and immutable | Tuple | Arrays used as tuple-like values | Multiple return values, structs |
| Destructuring | `Make Name and Score be Player`, checked for count or names | Tuple/list unpacking | Array/object destructuring | Multiple assignment, no general object destructuring |
| Records or structs | `Record User` with `Has Name as String` | Dataclasses or namedtuple | Objects or classes | Structs |
| Objects or classes | `Object Counter` with teachings and enforced private members | Built in | Built in prototypes/classes | No classes |
| Interfaces or traits | `Contract Jsonable` | Protocols through typing | Structural conventions or TypeScript | Interfaces built in |
| Inheritance | Single object inheritance with plain `Use Parent` calls | Multiple inheritance | Prototype chain/classes | No class inheritance |
| Generics | `List of String`, no angle brackets | Type hints use brackets | JavaScript none, TypeScript uses angle brackets | Angle brackets |
| Union types | `Type Command means Add Command or Quit Command` | Type hints | TypeScript only | Usually interfaces or custom sum-like patterns |
| Error model | `Result`, `Need`, `Try/Catch/Finally`, plain English messages | Exceptions | Exceptions and promises | Error values |
| Async | `Async`, `Await`, `Async All`, `Async Race`, no callbacks | `async` and `await` | `async`, `await`, callbacks, promises | Goroutines and channels, no async keyword |
| Concurrency | `Spawn` plus typed checked channels, no data races | Threads, asyncio, multiprocessing | Event loop, workers | Goroutines and channels |
| Standard library | Math, String, List, Map, File, Http, Json, Time, OS, Regex, Async built in | Large standard library | Smaller runtime stdlib, host dependent | Strong standard library |
| Package manager | `271 add package_name` | pip, poetry, uv, others | npm, pnpm, yarn, others | `go get` |
| Tooling | Scaffold, doctor, semantic check, run, REPL, formatter, linter, tests, docs, compile cache, Python emitter, packaging, LSP built in | Tools vary by environment | Tools vary widely | Strong built-in tooling |
| Safety stance | Checked math, explicit absence, type-safe mutation, typed collection updates, semantic checks, ignored-Result errors, runtime traces | Flexible, some mistakes caught late | Very flexible, many coercions | Type safe, explicit errors, some runtime panics |
| Best fit | Beginners through production systems where clarity matters | Scripting, data, apps, education | Web apps and ecosystem-heavy work | Services, CLIs, infrastructure |
